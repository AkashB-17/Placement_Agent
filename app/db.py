"""
Persistence for policies, JDs, students and profiles.

Two backends behind one set of functions:
* Postgres (hosted Supabase) when DATABASE_URL is set. Its schema is owned by
  supabase/migrations/; this module never creates tables there.
* SQLite otherwise (tests and the offline demo), created by init_db().

Queries are written once with "?" placeholders and the same column names in both
schemas; JSON columns are jsonb in Postgres and text in SQLite.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
import weakref
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from app.config import get_settings

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    email TEXT,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'student'
        CHECK (role IN ('student', 'officer', 'recruiter', 'admin')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS policies (
    id TEXT PRIMARY KEY,
    source_text TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jds (
    id TEXT PRIMARY KEY,
    source_text TEXT NOT NULL,
    requirements_json TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    branch TEXT NOT NULL,
    batch TEXT NOT NULL,
    cgpa REAL NOT NULL,
    active_backlogs INTEGER NOT NULL,
    is_placed INTEGER NOT NULL DEFAULT 0,
    resume_text TEXT,
    parsed_json TEXT NOT NULL,
    resume_path TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Staged auto-apply (mirrors supabase/migrations/20261117000000_auto_apply.sql).
-- Timestamps are UTC ISO-8601 strings, so they sort and compare as text.
CREATE TABLE IF NOT EXISTS auto_apply_preferences (
    student_id TEXT PRIMARY KEY REFERENCES students (id) ON DELETE CASCADE,
    enabled INTEGER NOT NULL DEFAULT 0,
    min_score REAL NOT NULL CHECK (min_score BETWEEN 0 AND 100),
    excluded_companies TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    jd_id TEXT NOT NULL REFERENCES jds (id) ON DELETE CASCADE,
    policy_id TEXT NOT NULL REFERENCES policies (id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'withdrawn', 'submitted')),
    score REAL NOT NULL,
    match_json TEXT NOT NULL,
    resume_path TEXT,
    resume_sha TEXT NOT NULL,
    created_at TEXT NOT NULL,
    release_at TEXT NOT NULL,
    decided_at TEXT,
    created_by TEXT,
    UNIQUE (student_id, jd_id),
    CHECK (release_at > created_at),
    CHECK ((status = 'pending') = (decided_at IS NULL))
);

CREATE INDEX IF NOT EXISTS applications_pending_release_idx ON applications (release_at) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    application_id TEXT REFERENCES applications (id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('application_pending', 'application_submitted', 'application_withdrawn')),
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT
);

-- Score cache (mirrors supabase/migrations/20261117120000_score_cache.sql).
CREATE TABLE IF NOT EXISTS score_cache (
    cache_key TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    jd_id TEXT NOT NULL REFERENCES jds (id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    breakdown_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auto_apply_runs (
    id TEXT PRIMARY KEY,
    jd_id TEXT NOT NULL REFERENCES jds (id) ON DELETE CASCADE,
    policy_id TEXT,
    trigger TEXT NOT NULL CHECK (trigger IN ('upload', 'manual')),
    status TEXT NOT NULL CHECK (status IN ('completed', 'skipped', 'failed')),
    ran_at TEXT NOT NULL,
    applied INTEGER NOT NULL DEFAULT 0,
    skipped TEXT NOT NULL DEFAULT '[]',
    not_opted_in INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    actor TEXT
);

CREATE TABLE IF NOT EXISTS registration_requests (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    branch TEXT NOT NULL,
    batch TEXT NOT NULL,
    cgpa REAL NOT NULL,
    active_backlogs INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    submitted_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);
"""

# Columns added after the first SQLite schema; added in place for existing local DBs.
_SQLITE_ADDED_COLUMNS = {
    "policies": ["created_by TEXT"],
    "jds": [
        "created_by TEXT",
        "deadline_override TEXT",
        "deadline_changed_at TEXT",
        "deadline_changed_by TEXT",
        "requirements_edited TEXT",
        "edited_at TEXT",
        "edited_by TEXT",
    ],
    "students": [
        "is_placed INTEGER NOT NULL DEFAULT 0",
        "email TEXT",
        "resume_path TEXT",
        "created_by TEXT",
        "resume_updated_at TEXT",
    ],
}

_STUDENT_FULL_COLUMNS = (
    "id, name, email, branch, batch, cgpa, active_backlogs, is_placed, "
    "resume_text, parsed_json, resume_path, resume_updated_at"
)


def make_document_id(*parts: str) -> str:
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def using_postgres() -> bool:
    return bool(get_settings().database_url)


# ── Connection handling ─────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """SQLite connection (tests inspect the local DB directly through this)."""
    path = Path(get_settings().sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# Postgres: a small pool of open connections. The hosted database is far away (opening a
# connection costs 1.5-2.5 s, a query ~0.3 s), so reusing connections is the main speed-up.
_POOL_MAX_SIZE = 5
_RECHECK_AFTER_IDLE_SECONDS = 30.0
_pool: ConnectionPool | None = None
_pool_url: str | None = None
_pool_lock = threading.Lock()
_last_returned: weakref.WeakKeyDictionary[Any, float] = weakref.WeakKeyDictionary()


def _mark_returned(conn: psycopg.Connection) -> None:
    _last_returned[conn] = time.monotonic()


def _check_if_idle(conn: psycopg.Connection) -> None:
    """Ping a connection only if it sat idle a while (a dead one is then replaced).

    Pinging on every checkout would add a full round trip to each query."""
    if time.monotonic() - _last_returned.get(conn, 0.0) > _RECHECK_AFTER_IDLE_SECONDS:
        conn.execute("SELECT 1")


def _get_pool() -> ConnectionPool:
    global _pool, _pool_url
    url = get_settings().database_url
    with _pool_lock:
        if _pool is None or _pool_url != url:
            if _pool is not None:
                _pool.close()
            _pool = ConnectionPool(
                url,
                min_size=1,
                max_size=_POOL_MAX_SIZE,
                # Every call in this module is one statement, so autocommit loses nothing and
                # saves the separate COMMIT round trip. Multi-statement work would need
                # an explicit `with conn.transaction():`.
                kwargs={"row_factory": dict_row, "autocommit": True},
                check=_check_if_idle,
                reset=_mark_returned,
                max_idle=300,
                timeout=15,
                name="placement",
                open=True,
            )
            _pool_url = url
        return _pool


def open_pool() -> None:
    """Called at startup so the first request doesn't pay for the connection."""
    if using_postgres():
        try:
            _get_pool().wait(timeout=15)
        except PoolTimeout as exc:
            raise HTTPException(status_code=503, detail="Database unavailable.") from exc


def close_pool() -> None:
    global _pool, _pool_url
    with _pool_lock:
        if _pool is not None:
            _pool.close()
        _pool, _pool_url = None, None


@contextmanager
def _transaction() -> Iterator[Any]:
    """Yield a cursor; commit on success, roll back on error, release the connection."""
    if using_postgres():
        try:
            # pool.connection() commits on success, rolls back on error, and discards a
            # connection left broken so the pool replaces it.
            with _get_pool().connection() as conn, conn.cursor() as cursor:
                yield cursor
        except (PoolTimeout, psycopg.OperationalError) as exc:
            # Unreachable, or the connection died mid-query. Never echo the connection
            # string: it contains the database password.
            raise HTTPException(status_code=503, detail="Database unavailable.") from exc
        return

    conn = get_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _atomic() -> Iterator[Any]:
    """Like _transaction, but for several statements that must commit together.

    The pooled Postgres connections are in autocommit mode, so this opens an explicit
    transaction. SQLite's _transaction already commits once, at the end."""
    if not using_postgres():
        with _transaction() as cursor:
            yield cursor
        return
    try:
        with _get_pool().connection() as conn, conn.transaction(), conn.cursor() as cursor:
            yield cursor
    except (PoolTimeout, psycopg.OperationalError) as exc:
        raise HTTPException(status_code=503, detail="Database unavailable.") from exc


def _sql(query: str) -> str:
    return query.replace("?", "%s") if using_postgres() else query


def _execute(query: str, params: tuple = ()) -> None:
    with _transaction() as cur:
        cur.execute(_sql(query), params)


def _fetchall(query: str, params: tuple = ()) -> list[dict[str, Any]]:
    with _transaction() as cur:
        cur.execute(_sql(query), params)
        return [dict(row) for row in cur.fetchall()]


def _fetchone(query: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = _fetchall(query, params)
    return rows[0] if rows else None


def _json_param(serialized: str) -> Any:
    return Jsonb(json.loads(serialized)) if using_postgres() else serialized


def _json_value(value: Any) -> Any:
    """jsonb arrives as dict/list from psycopg; SQLite stores text."""
    return json.loads(value) if isinstance(value, str) else value


def init_db() -> None:
    if using_postgres():
        # The schema is applied from supabase/migrations/. Fail fast if it isn't.
        try:
            _fetchone("SELECT 1 AS ok FROM profiles LIMIT 1")
        except psycopg.errors.UndefinedTable as exc:
            raise RuntimeError(
                "Supabase tables are missing. Run supabase/migrations/*.sql in the SQL Editor."
            ) from exc
        try:
            _fetchone("SELECT 1 AS ok FROM applications LIMIT 1")
        except psycopg.errors.UndefinedTable as exc:
            raise RuntimeError(
                "Auto-apply tables are missing. Apply supabase/migrations/20261117000000_auto_apply.sql "
                "(npx supabase@latest db push --linked)."
            ) from exc
        try:
            _fetchone("SELECT resume_updated_at FROM students LIMIT 1")
        except psycopg.errors.UndefinedColumn as exc:
            raise RuntimeError(
                "The student CV migration is missing. Apply supabase/migrations/20261120000000_student_cv.sql "
                "(npx supabase@latest db push --linked)."
            ) from exc
        try:
            _fetchone("SELECT 1 AS ok FROM registration_requests LIMIT 1")
        except psycopg.errors.UndefinedTable as exc:
            raise RuntimeError(
                "The registration requests table is missing. Apply supabase/migrations/20261130000000_registration_requests.sql "
                "(npx supabase@latest db push --remote)."
            ) from exc
        try:
            _fetchone("SELECT 1 AS ok FROM auto_apply_runs LIMIT 1")
        except psycopg.errors.UndefinedTable as exc:
            raise RuntimeError(
                "The auto-apply runs table is missing. Apply supabase/migrations/20261129000000_auto_apply_runs.sql "
                "(npx supabase@latest db push --remote)."
            ) from exc
        try:
            _fetchone("SELECT 1 AS ok FROM app_settings LIMIT 1")
        except psycopg.errors.UndefinedTable as exc:
            raise RuntimeError(
                "The app settings table is missing. Apply supabase/migrations/20261128000000_app_settings.sql "
                "(npx supabase@latest db push --remote)."
            ) from exc
        try:
            _fetchone("SELECT requirements_edited FROM jds LIMIT 1")
        except psycopg.errors.UndefinedColumn as exc:
            raise RuntimeError(
                "The JD edits migration is missing. Apply supabase/migrations/20261127000000_jd_edits.sql "
                "(npx supabase@latest db push --linked)."
            ) from exc
        try:
            _fetchone("SELECT deadline_override FROM jds LIMIT 1")
        except psycopg.errors.UndefinedColumn as exc:
            raise RuntimeError(
                "The JD deadline migration is missing. Apply supabase/migrations/20261126000000_jd_deadline.sql "
                "(npx supabase@latest db push --linked)."
            ) from exc
        try:
            _fetchone("SELECT 1 AS ok FROM score_cache LIMIT 1")
        except psycopg.errors.UndefinedTable as exc:
            raise RuntimeError(
                "The score cache table is missing. Apply supabase/migrations/20261117120000_score_cache.sql "
                "(npx supabase@latest db push --linked)."
            ) from exc
        return

    conn = get_connection()
    try:
        conn.executescript(SQLITE_SCHEMA)
        for table, columns in _SQLITE_ADDED_COLUMNS.items():
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column in columns:
                if column.split()[0] not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        conn.commit()
    finally:
        conn.close()


# ── Profiles ────────────────────────────────────────────────────────────────

# Roles are read on every request. On Postgres each read is a network round trip, so
# auth uses a short-lived cache. A role change made through the API clears the entry at
# once; one made by hand in the SQL Editor applies within PROFILE_CACHE_SECONDS.
PROFILE_CACHE_SECONDS = 60.0
_profile_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def _profile(row: dict[str, Any]) -> dict[str, Any]:
    # profiles.id is a uuid column in Postgres: psycopg returns uuid.UUID, the API uses strings.
    return {**row, "id": str(row["id"])}


def get_profile(user_id: str) -> dict[str, Any] | None:
    row = _fetchone("SELECT id, email, full_name, role FROM profiles WHERE id = ?", (user_id,))
    return _profile(row) if row else None


def get_profile_cached(user_id: str) -> dict[str, Any] | None:
    """get_profile with a short cache on Postgres. SQLite is local and fast, so uncached."""
    if not using_postgres():
        return get_profile(user_id)
    now = time.monotonic()
    hit = _profile_cache.get(user_id)
    if hit and hit[0] > now:
        return hit[1]
    profile = get_profile(user_id)
    if profile is not None:  # don't cache "missing": the sign-up trigger may be catching up
        _profile_cache[user_id] = (now + PROFILE_CACHE_SECONDS, profile)
    return profile


def clear_profile_cache(user_id: str | None = None) -> None:
    if user_id is None:
        _profile_cache.clear()
    else:
        _profile_cache.pop(user_id, None)


def list_profiles() -> list[dict[str, Any]]:
    return [_profile(row) for row in _fetchall("SELECT id, email, role FROM profiles ORDER BY role, email")]


def set_profile_role(user_id: str, role: str) -> None:
    _execute("UPDATE profiles SET role = ? WHERE id = ?", (role, user_id))
    clear_profile_cache(user_id)


def upsert_profile(user_id: str, email: str | None, role: str = "student") -> None:
    """SQLite only: in Supabase the auth trigger creates profiles."""
    _execute(
        """
        INSERT INTO profiles (id, email, role) VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET email = excluded.email, role = excluded.role
        """,
        (str(user_id), email, role),
    )


# ── Writes ──────────────────────────────────────────────────────────────────

def upsert_policy(policy_id: str, source_text: str, rules_json: str, created_by: str | None = None) -> None:
    _execute(
        """
        INSERT INTO policies (id, source_text, rules_json, created_by)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            source_text = excluded.source_text,
            rules_json = excluded.rules_json,
            created_by = COALESCE(policies.created_by, excluded.created_by)
        """,
        (policy_id, source_text, _json_param(rules_json), created_by),
    )


def upsert_jd(jd_id: str, source_text: str, requirements_json: str, created_by: str | None = None) -> None:
    _execute(
        """
        INSERT INTO jds (id, source_text, requirements_json, created_by)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            source_text = excluded.source_text,
            requirements_json = excluded.requirements_json,
            created_by = COALESCE(jds.created_by, excluded.created_by)
        """,
        (jd_id, source_text, _json_param(requirements_json), created_by),
    )


def upsert_student_record(
    student_id: str,
    name: str,
    branch: str,
    batch: str,
    cgpa: float,
    active_backlogs: int,
    is_placed: bool = False,
    email: str | None = None,
    created_by: str | None = None,
) -> None:
    """Create or update the academic record the placement office owns.

    Never touches the CV columns of an existing record: the student owns their CV, so an
    officer correcting a CGPA must not wipe an uploaded CV. A new record starts with no CV."""
    _execute(
        """
        INSERT INTO students (
            id, name, email, branch, batch, cgpa, active_backlogs, is_placed,
            resume_text, parsed_json, resume_path, created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            email = COALESCE(excluded.email, students.email),
            branch = excluded.branch,
            batch = excluded.batch,
            cgpa = excluded.cgpa,
            active_backlogs = excluded.active_backlogs,
            is_placed = excluded.is_placed,
            created_by = COALESCE(students.created_by, excluded.created_by)
        """,
        (
            student_id,
            name,
            email,
            branch,
            batch,
            cgpa,
            active_backlogs,
            is_placed if using_postgres() else int(is_placed),
            _json_param("{}"),
            created_by,
        ),
    )


def update_student_record(
    student_id: str,
    name: str,
    email: str | None,
    branch: str,
    batch: str,
    cgpa: float,
    active_backlogs: int,
    is_placed: bool,
) -> bool:
    """The office edits an existing academic record. Unlike upsert_student_record, the email
    is set as given (it can be changed or removed). The id and CV columns never change,
    so applications, scores and the student's CV stay attached. False if no such student."""
    row = _fetchone(
        """
        UPDATE students SET name = ?, email = ?, branch = ?, batch = ?, cgpa = ?,
            active_backlogs = ?, is_placed = ?
        WHERE id = ?
        RETURNING id
        """,
        (
            name, email, branch, batch, cgpa, active_backlogs,
            is_placed if using_postgres() else int(is_placed), student_id,
        ),
    )
    return row is not None


def set_student_resume(
    student_id: str, resume_text: str, parsed_json: str, resume_path: str | None, now: datetime
) -> None:
    """Make this the student's current CV. Earlier files stay in storage untouched, so
    applications that pinned them still point at what was scored."""
    _execute(
        "UPDATE students SET resume_text = ?, parsed_json = ?, resume_path = ?, resume_updated_at = ? WHERE id = ?",
        (resume_text, _json_param(parsed_json), resume_path, _ts(now), student_id),
    )


def find_student_id(email: str | None, name: str, branch: str, batch: str) -> str | None:
    """An existing record for this student, so re-adding them updates instead of duplicating.

    Matched by login email when there is one, otherwise by name + branch + batch."""
    if email:
        row = _fetchone(
            "SELECT id FROM students WHERE lower(email) = lower(?) ORDER BY created_at DESC LIMIT 1", (email,)
        )
    else:
        row = _fetchone(
            "SELECT id FROM students WHERE lower(name) = lower(?) AND branch = ? AND batch = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (name, branch, batch),
        )
    return row["id"] if row else None


# ── Reads ───────────────────────────────────────────────────────────────────

def list_policies() -> list[dict]:
    rows = _fetchall("SELECT id, rules_json FROM policies ORDER BY created_at DESC")
    return [{"id": row["id"], **_json_value(row["rules_json"])} for row in rows]


def get_policy(policy_id: str) -> dict | None:
    row = _fetchone("SELECT id, source_text, rules_json FROM policies WHERE id = ?", (policy_id,))
    if row is None:
        return None
    return {"id": row["id"], "source_text": row["source_text"], "rules": _json_value(row["rules_json"])}


_JD_DEADLINE_COLUMNS = "deadline_override, deadline_changed_at, requirements_edited, edited_at, created_at"


def _jd_requirements(row: dict[str, Any]) -> dict[str, Any]:
    """The JD's requirements as the app uses them: an admin's edit replaces the extracted
    requirements, and a changed deadline replaces the deadline."""
    edited = _json_value(row["requirements_edited"]) if row["requirements_edited"] else None
    requirements = dict(edited or _json_value(row["requirements_json"]) or {})
    if row["deadline_override"]:
        requirements["deadline"] = row["deadline_override"]
    return requirements


def _jd_deadline_meta(row: dict[str, Any]) -> dict[str, Any]:
    extracted = (_json_value(row["requirements_json"]) or {}).get("deadline")
    changed = bool(row["deadline_override"])
    return {
        "original_deadline": extracted if changed else None,
        "deadline_changed_at": _dt(row["deadline_changed_at"]) if changed else None,
        "edited_at": _dt(row["edited_at"]),
        "posted_at": _dt(row["created_at"]),
    }


def list_jds() -> list[dict]:
    rows = _fetchall(
        f"SELECT id, requirements_json, created_by, {_JD_DEADLINE_COLUMNS} FROM jds ORDER BY created_at DESC"
    )
    return [
        {"id": row["id"], "created_by": _str_or_none(row["created_by"]), **_jd_requirements(row), **_jd_deadline_meta(row)}
        for row in rows
    ]


def list_jd_rows() -> list[dict[str, Any]]:
    """Every JD with its requirements and when it was posted, newest first."""
    rows = _fetchall(
        f"SELECT id, requirements_json, {_JD_DEADLINE_COLUMNS} FROM jds ORDER BY created_at DESC"
    )
    return [
        {"id": row["id"], "requirements": _jd_requirements(row), "created_at": _dt(row["created_at"]), **_jd_deadline_meta(row)}
        for row in rows
    ]


def get_jd(jd_id: str) -> dict | None:
    row = _fetchone(
        f"SELECT id, source_text, requirements_json, created_by, {_JD_DEADLINE_COLUMNS} FROM jds WHERE id = ?",
        (jd_id,),
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "source_text": row["source_text"],
        "requirements": _jd_requirements(row),
        "created_by": _str_or_none(row["created_by"]),
        **_jd_deadline_meta(row),
    }


def get_jd_extracted_requirements(jd_id: str) -> dict[str, Any] | None:
    """The requirements as extracted from the JD text, ignoring any edit or deadline change."""
    row = _fetchone("SELECT requirements_json FROM jds WHERE id = ?", (jd_id,))
    return _json_value(row["requirements_json"]) if row else None


def set_jd_requirements_edited(jd_id: str, requirements_json: str, now: datetime, edited_by: str | None) -> bool:
    """Save an admin's edit of a JD's requirements (the extracted ones stay as they were)."""
    row = _fetchone(
        "UPDATE jds SET requirements_edited = ?, edited_at = ?, edited_by = ? WHERE id = ? RETURNING id",
        (_json_param(requirements_json), _ts(now), edited_by, jd_id),
    )
    return row is not None


def delete_jd(jd_id: str, now: datetime, message: str) -> dict[str, Any] | None:
    """Remove a job and everything that hangs off it, in one transaction.

    Deletes are explicit (SQLite doesn't enforce the foreign keys' ON DELETE CASCADE):
    the job's applications, their notifications, and its cached scores. Each student who
    had a pending or sent application gets `message` (a notification with no application,
    since that row is gone). None if there is no such job."""
    with _atomic() as cur:
        cur.execute(_sql("SELECT student_id, status FROM applications WHERE jd_id = ?"), (jd_id,))
        applications = [dict(row) for row in cur.fetchall()]
        cur.execute(
            _sql("DELETE FROM notifications WHERE application_id IN (SELECT id FROM applications WHERE jd_id = ?)"),
            (jd_id,),
        )
        cur.execute(_sql("DELETE FROM applications WHERE jd_id = ?"), (jd_id,))
        cur.execute(_sql("DELETE FROM score_cache WHERE jd_id = ?"), (jd_id,))
        cur.execute(_sql("DELETE FROM auto_apply_runs WHERE jd_id = ?"), (jd_id,))
        cur.execute(_sql("DELETE FROM jds WHERE id = ? RETURNING id"), (jd_id,))
        if cur.fetchone() is None:
            return None
        notified = sorted({a["student_id"] for a in applications if a["status"] in ("pending", "submitted")})
        for student_id in notified:
            _insert_notification(cur, student_id, None, "application_withdrawn", message, now)
    return {"applications_removed": len(applications), "students_notified": len(notified)}


def change_jd_deadline(
    jd_id: str,
    deadline: str,
    changed_at: datetime,
    changed_by: str | None,
    moves: list[dict[str, Any]],
) -> list[str]:
    """Set a JD's deadline and move pending applications earlier, in one transaction.

    Each move is {id, student_id, release_at, message}. A move only applies if the
    application is still pending and would be released later than the new time (a
    withdrawal or release that commits first wins). Returns the ids actually moved;
    each of those students gets the move's notification."""
    moved: list[str] = []
    with _atomic() as cur:
        cur.execute(
            _sql(
                "UPDATE jds SET deadline_override = ?, deadline_changed_at = ?, deadline_changed_by = ? "
                "WHERE id = ? RETURNING id"
            ),
            (deadline, _ts(changed_at), changed_by, jd_id),
        )
        if cur.fetchone() is None:
            return moved
        for move in moves:
            cur.execute(
                _sql(
                    "UPDATE applications SET release_at = ? "
                    "WHERE id = ? AND status = 'pending' AND release_at > ? RETURNING id"
                ),
                (_ts(move["release_at"]), move["id"], _ts(move["release_at"])),
            )
            if cur.fetchone() is None:
                continue
            _insert_notification(cur, move["student_id"], move["id"], "application_pending", move["message"], changed_at)
            moved.append(move["id"])
    return moved


def list_students() -> list[dict]:
    rows = _fetchall(
        "SELECT id, name, email, branch, batch, cgpa, active_backlogs, is_placed, "
        "CASE WHEN resume_text IS NOT NULL AND resume_text <> '' THEN 1 ELSE 0 END AS has_resume "
        "FROM students ORDER BY created_at DESC"
    )
    return [{**row, "is_placed": bool(row["is_placed"]), "has_resume": bool(row["has_resume"])} for row in rows]


def _student(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "branch": row["branch"],
        "batch": row["batch"],
        "cgpa": float(row["cgpa"]),
        "active_backlogs": row["active_backlogs"],
        "is_placed": bool(row["is_placed"]),
        "resume_text": row["resume_text"] or "",
        "parsed": _json_value(row["parsed_json"]) or {},
        "resume_path": row["resume_path"],
        "resume_updated_at": _dt(row["resume_updated_at"]),
    }


def get_student(student_id: str) -> dict | None:
    row = _fetchone(f"SELECT {_STUDENT_FULL_COLUMNS} FROM students WHERE id = ?", (student_id,))
    return _student(row) if row else None


def get_student_by_email(email: str) -> dict | None:
    row = _fetchone(
        f"SELECT {_STUDENT_FULL_COLUMNS} FROM students WHERE lower(email) = lower(?) "
        "ORDER BY created_at DESC LIMIT 1",
        (email,),
    )
    return _student(row) if row else None


def get_all_students() -> list[dict]:
    """Return all students with full data for ranking."""
    return [_student(row) for row in _fetchall(f"SELECT {_STUDENT_FULL_COLUMNS} FROM students")]


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


# ── Timestamps ──────────────────────────────────────────────────────────────

def _ts(value: datetime) -> Any:
    """Bind a timestamp: timestamptz in Postgres, a UTC ISO string in SQLite.

    Microseconds, like Postgres: an application made in a deadline's last second has
    created_at and release_at within the same second, and CHECK (release_at > created_at)
    must still hold. (Older second-precision strings still sort correctly against these.)"""
    value = value.astimezone(UTC)
    return value if using_postgres() else value.isoformat(timespec="microseconds")


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _bool(value: Any) -> Any:
    return bool(value) if using_postgres() else int(bool(value))


# ── Auto-apply: preferences ─────────────────────────────────────────────────

def get_preferences(student_id: str) -> dict[str, Any] | None:
    row = _fetchone(
        "SELECT student_id, enabled, min_score, excluded_companies, updated_at "
        "FROM auto_apply_preferences WHERE student_id = ?",
        (student_id,),
    )
    if row is None:
        return None
    return {
        "student_id": row["student_id"],
        "enabled": bool(row["enabled"]),
        "min_score": float(row["min_score"]),
        "excluded_companies": list(_json_value(row["excluded_companies"]) or []),
        "updated_at": _dt(row["updated_at"]),
    }


def upsert_preferences(
    student_id: str, enabled: bool, min_score: float, excluded_companies: list[str], now: datetime
) -> None:
    _execute(
        """
        INSERT INTO auto_apply_preferences (student_id, enabled, min_score, excluded_companies, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(student_id) DO UPDATE SET
            enabled = excluded.enabled,
            min_score = excluded.min_score,
            excluded_companies = excluded.excluded_companies,
            updated_at = excluded.updated_at
        """,
        (student_id, _bool(enabled), min_score, _json_param(json.dumps(excluded_companies)), _ts(now)),
    )


def list_opted_in_students() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(student with full data, preferences) for every student with auto-apply on."""
    columns = ", ".join(f"s.{c.strip()}" for c in _STUDENT_FULL_COLUMNS.split(","))
    rows = _fetchall(
        f"SELECT {columns}, p.min_score AS pref_min_score, p.excluded_companies AS pref_excluded "
        "FROM students s JOIN auto_apply_preferences p ON p.student_id = s.id WHERE p.enabled = ?",
        (_bool(True),),
    )
    return [
        (
            _student(row),
            {
                "min_score": float(row["pref_min_score"]),
                "excluded_companies": list(_json_value(row["pref_excluded"]) or []),
            },
        )
        for row in rows
    ]


# ── Auto-apply: applications ────────────────────────────────────────────────

_APPLICATION_SELECT = (
    "SELECT a.id, a.student_id, a.jd_id, a.policy_id, a.status, a.score, a.match_json, a.resume_path, "
    "a.resume_sha, a.created_at, a.release_at, a.decided_at, s.name AS student_name, "
    "j.requirements_json AS jd_requirements, j.created_by AS jd_created_by, p.role AS created_by_role "
    "FROM applications a JOIN students s ON s.id = a.student_id JOIN jds j ON j.id = a.jd_id "
    "LEFT JOIN profiles p ON p.id = a.created_by"
)


def _application(row: dict[str, Any]) -> dict[str, Any]:
    requirements = _json_value(row["jd_requirements"]) or {}
    return {
        "id": row["id"],
        "student_id": row["student_id"],
        "student_name": row["student_name"],
        "jd_id": row["jd_id"],
        "company": requirements.get("company"),
        "role": requirements.get("role"),
        "jd_created_by": _str_or_none(row["jd_created_by"]),
        "policy_id": row["policy_id"],
        "status": row["status"],
        "score": float(row["score"]),
        "match": _json_value(row["match_json"]),
        "resume_path": row["resume_path"],
        "resume_sha": row["resume_sha"],
        "created_at": _dt(row["created_at"]),
        "release_at": _dt(row["release_at"]),
        "decided_at": _dt(row["decided_at"]),
        # A student applying from their job board is "manual"; an officer's run is "auto".
        "source": "manual" if row["created_by_role"] == "student" else "auto",
    }


def application_statuses_for_jd(jd_id: str) -> dict[str, str]:
    """student_id -> status of their application to this JD (any status)."""
    rows = _fetchall("SELECT student_id, status FROM applications WHERE jd_id = ?", (jd_id,))
    return {row["student_id"]: row["status"] for row in rows}


def active_application_counts() -> dict[str, int]:
    """student_id -> number of pending or submitted applications."""
    rows = _fetchall(
        "SELECT student_id, COUNT(*) AS n FROM applications "
        "WHERE status IN ('pending', 'submitted') GROUP BY student_id"
    )
    return {row["student_id"]: int(row["n"]) for row in rows}


def create_application(application: dict[str, Any], notification_message: str) -> bool:
    """Insert a pending application and its notification together.

    Returns False (and writes nothing) if the student already has an application to
    this JD, so concurrent auto-apply runs can't double-apply."""
    with _atomic() as cur:
        cur.execute(
            _sql(
                """
                INSERT INTO applications (
                    id, student_id, jd_id, policy_id, status, score, match_json,
                    resume_path, resume_sha, created_at, release_at, created_by
                )
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (student_id, jd_id) DO NOTHING
                RETURNING id
                """
            ),
            (
                application["id"],
                application["student_id"],
                application["jd_id"],
                application["policy_id"],
                application["score"],
                _json_param(application["match_json"]),
                application["resume_path"],
                application["resume_sha"],
                _ts(application["created_at"]),
                _ts(application["release_at"]),
                application["created_by"],
            ),
        )
        if cur.fetchone() is None:
            return False
        _insert_notification(
            cur,
            application["student_id"],
            application["id"],
            "application_pending",
            notification_message,
            application["created_at"],
        )
        return True


def release_due_applications(now: datetime, message: Callable[[dict[str, Any]], str]) -> list[str]:
    """Submit every pending application whose withdraw window has closed.

    One conditional UPDATE: idempotent, safe to run from several places at once, and a
    withdrawal that commits first simply leaves nothing to release. Returns released ids."""
    with _atomic() as cur:
        cur.execute(
            _sql(
                "UPDATE applications SET status = 'submitted', decided_at = ? "
                "WHERE status = 'pending' AND release_at <= ? RETURNING id, student_id, jd_id"
            ),
            (_ts(now), _ts(now)),
        )
        released = [dict(row) for row in cur.fetchall()]
        if not released:
            return []
        jd_ids = sorted({row["jd_id"] for row in released})
        placeholders = ", ".join("?" for _ in jd_ids)
        cur.execute(_sql(f"SELECT id, requirements_json FROM jds WHERE id IN ({placeholders})"), tuple(jd_ids))
        jds = {row["id"]: _json_value(row["requirements_json"]) or {} for row in cur.fetchall()}
        for row in released:
            jd = jds.get(row["jd_id"], {})
            _insert_notification(
                cur,
                row["student_id"],
                row["id"],
                "application_submitted",
                message({"company": jd.get("company"), "role": jd.get("role")}),
                now,
            )
        return [row["id"] for row in released]


def withdraw_application(application_id: str, student_id: str, now: datetime, message: str) -> bool:
    """Withdraw if it is the student's, still pending, and inside its window."""
    with _atomic() as cur:
        cur.execute(
            _sql(
                "UPDATE applications SET status = 'withdrawn', decided_at = ? "
                "WHERE id = ? AND student_id = ? AND status = 'pending' AND release_at > ? RETURNING id"
            ),
            (_ts(now), application_id, student_id, _ts(now)),
        )
        if cur.fetchone() is None:
            return False
        _insert_notification(cur, student_id, application_id, "application_withdrawn", message, now)
        return True


def reapply_application(application: dict[str, Any], notification_message: str) -> str | None:
    """A student re-applies to a job they withdrew from: the same row goes back to pending
    with a fresh snapshot (CV, score, window). Only a withdrawn row changes, so a
    pending or submitted application is never touched. Returns the application id, or None."""
    with _atomic() as cur:
        cur.execute(
            _sql(
                """
                UPDATE applications SET
                    status = 'pending', decided_at = NULL, policy_id = ?, score = ?, match_json = ?,
                    resume_path = ?, resume_sha = ?, created_at = ?, release_at = ?, created_by = ?
                WHERE student_id = ? AND jd_id = ? AND status = 'withdrawn'
                RETURNING id
                """
            ),
            (
                application["policy_id"],
                application["score"],
                _json_param(application["match_json"]),
                application["resume_path"],
                application["resume_sha"],
                _ts(application["created_at"]),
                _ts(application["release_at"]),
                application["created_by"],
                application["student_id"],
                application["jd_id"],
            ),
        )
        row = cur.fetchone()
        if row is None:
            return None
        _insert_notification(
            cur, application["student_id"], row["id"], "application_pending",
            notification_message, application["created_at"],
        )
        return row["id"]


def get_application(application_id: str) -> dict[str, Any] | None:
    row = _fetchone(f"{_APPLICATION_SELECT} WHERE a.id = ?", (application_id,))
    return _application(row) if row else None


def list_applications(
    *,
    student_id: str | None = None,
    jd_id: str | None = None,
    status: str | None = None,
    jd_created_by: str | None = None,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    filters = (("a.student_id", student_id), ("a.jd_id", jd_id), ("a.status", status), ("j.created_by", jd_created_by))
    for column, value in filters:
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = _fetchall(f"{_APPLICATION_SELECT}{where} ORDER BY a.created_at DESC, s.name", tuple(params))
    return [_application(row) for row in rows]


# ── Notifications ───────────────────────────────────────────────────────────

def _insert_notification(
    cur: Any, student_id: str, application_id: str | None, kind: str, message: str, now: datetime
) -> None:
    cur.execute(
        _sql(
            "INSERT INTO notifications (id, student_id, application_id, kind, message, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        ),
        (uuid.uuid4().hex, student_id, application_id, kind, message, _ts(now)),
    )


def list_notifications(student_id: str, limit: int = 30) -> list[dict[str, Any]]:
    rows = _fetchall(
        "SELECT id, application_id, kind, message, created_at, read_at FROM notifications "
        "WHERE student_id = ? ORDER BY created_at DESC LIMIT ?",
        (student_id, limit),
    )
    return [{**row, "created_at": _dt(row["created_at"]), "read": row["read_at"] is not None} for row in rows]


def mark_notifications_read(student_id: str, now: datetime) -> None:
    _execute(
        "UPDATE notifications SET read_at = ? WHERE student_id = ? AND read_at IS NULL",
        (_ts(now), student_id),
    )


# ── Score cache ─────────────────────────────────────────────────────────────

# ── Self sign-up: registration requests ───────────────────────────────────

_REGISTRATION_COLUMNS = (
    "user_id, email, name, branch, batch, cgpa, active_backlogs, status, submitted_at, decided_at, note"
)


def _registration(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "user_id": str(row["user_id"]),
        "cgpa": float(row["cgpa"]),
        "submitted_at": _dt(row["submitted_at"]),
        "decided_at": _dt(row["decided_at"]),
    }


def submit_registration_request(request: dict[str, Any], now: datetime) -> None:
    """Create or resubmit a student's request; resubmitting puts it back to pending.
    An approved request is never reopened (the caller checks the student isn't linked)."""
    _execute(
        """
        INSERT INTO registration_requests (
            user_id, email, name, branch, batch, cgpa, active_backlogs, status, submitted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        ON CONFLICT (user_id) DO UPDATE SET
            email = excluded.email, name = excluded.name, branch = excluded.branch,
            batch = excluded.batch, cgpa = excluded.cgpa, active_backlogs = excluded.active_backlogs,
            status = 'pending', submitted_at = excluded.submitted_at,
            decided_at = NULL, decided_by = NULL, note = NULL
        WHERE registration_requests.status <> 'approved'
        """,
        (
            request["user_id"], request["email"], request["name"], request["branch"], request["batch"],
            request["cgpa"], request["active_backlogs"], _ts(now),
        ),
    )


def get_registration_request(user_id: str) -> dict[str, Any] | None:
    row = _fetchone(f"SELECT {_REGISTRATION_COLUMNS} FROM registration_requests WHERE user_id = ?", (user_id,))
    return _registration(row) if row else None


def list_registration_requests(status: str | None = None) -> list[dict[str, Any]]:
    """Oldest pending first (first come, first served); decided ones newest first."""
    if status:
        order = "submitted_at ASC" if status == "pending" else "decided_at DESC"
        rows = _fetchall(
            f"SELECT {_REGISTRATION_COLUMNS} FROM registration_requests WHERE status = ? ORDER BY {order}", (status,)
        )
    else:
        rows = _fetchall(f"SELECT {_REGISTRATION_COLUMNS} FROM registration_requests ORDER BY submitted_at DESC")
    return [_registration(row) for row in rows]


def decide_registration_request(
    user_id: str, status: str, now: datetime, decided_by: str | None, note: str | None
) -> bool:
    """Approve or reject a request that is still pending. False if it isn't (anymore)."""
    row = _fetchone(
        "UPDATE registration_requests SET status = ?, decided_at = ?, decided_by = ?, note = ? "
        "WHERE user_id = ? AND status = 'pending' RETURNING user_id",
        (status, _ts(now), decided_by, note, user_id),
    )
    return row is not None


# ── Auto-apply run history ─────────────────────────────────────────────────

def record_auto_apply_run(run: dict[str, Any]) -> None:
    """Keep the outcome of one auto-apply run (see migration 20261129000000_auto_apply_runs)."""
    _execute(
        """
        INSERT INTO auto_apply_runs (
            id, jd_id, policy_id, trigger, status, ran_at, applied, skipped, not_opted_in, message, actor
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run["id"], run["jd_id"], run["policy_id"], run["trigger"], run["status"], _ts(run["ran_at"]),
            run["applied"], _json_param(json.dumps(run["skipped"])), run["not_opted_in"], run["message"], run["actor"],
        ),
    )


def list_auto_apply_runs(jd_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Runs newest first, for one JD or all of them."""
    where, params = ("WHERE jd_id = ?", (jd_id,)) if jd_id else ("", ())
    rows = _fetchall(
        f"SELECT id, jd_id, policy_id, trigger, status, ran_at, applied, skipped, not_opted_in, message "
        f"FROM auto_apply_runs {where} ORDER BY ran_at DESC LIMIT ?",
        (*params, limit),
    )
    return [
        {**row, "ran_at": _dt(row["ran_at"]), "skipped": _json_value(row["skipped"]) or []}
        for row in rows
    ]


# ── College-wide settings ──────────────────────────────────────────────────

def get_app_setting(key: str) -> dict[str, Any] | None:
    """{value, updated_at} for a setting an admin has changed, or None (use the default)."""
    row = _fetchone("SELECT value, updated_at FROM app_settings WHERE key = ?", (key,))
    if row is None:
        return None
    return {"value": _json_value(row["value"]), "updated_at": _dt(row["updated_at"])}


def set_app_setting(key: str, value: Any, now: datetime, updated_by: str | None) -> None:
    _execute(
        """
        INSERT INTO app_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)
        ON CONFLICT (key) DO UPDATE SET
            value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by
        """,
        (key, _json_param(json.dumps(value)), _ts(now), updated_by),
    )


def get_cached_score(cache_key: str) -> dict[str, Any] | None:
    row = _fetchone("SELECT breakdown_json FROM score_cache WHERE cache_key = ?", (cache_key,))
    return _json_value(row["breakdown_json"]) if row else None


def put_cached_score(
    cache_key: str, student_id: str, jd_id: str, model: str, breakdown_json: str, now: datetime
) -> None:
    """Store (or, on a forced re-score, replace) a verified score breakdown."""
    _execute(
        """
        INSERT INTO score_cache (cache_key, student_id, jd_id, model, breakdown_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (cache_key) DO UPDATE SET
            breakdown_json = excluded.breakdown_json,
            created_at = excluded.created_at
        """,
        (cache_key, student_id, jd_id, model, _json_param(breakdown_json), _ts(now)),
    )


def count_cached_scores() -> int:
    row = _fetchone("SELECT COUNT(*) AS n FROM score_cache")
    return int(row["n"]) if row else 0


# ── Source documents (for rebuilding the vector index) ─────────────────────

def list_policy_sources() -> list[tuple[str, str]]:
    return [(row["id"], row["source_text"]) for row in _fetchall("SELECT id, source_text FROM policies")]


def list_jd_sources() -> list[tuple[str, str]]:
    return [(row["id"], row["source_text"]) for row in _fetchall("SELECT id, source_text FROM jds")]
