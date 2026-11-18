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
"""

# Columns added after the first SQLite schema; added in place for existing local DBs.
_SQLITE_ADDED_COLUMNS = {
    "policies": ["created_by TEXT"],
    "jds": ["created_by TEXT"],
    "students": [
        "is_placed INTEGER NOT NULL DEFAULT 0",
        "email TEXT",
        "resume_path TEXT",
        "created_by TEXT",
    ],
}

_STUDENT_FULL_COLUMNS = (
    "id, name, email, branch, batch, cgpa, active_backlogs, is_placed, "
    "resume_text, parsed_json, resume_path"
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


def get_profile(user_id: str) -> dict[str, Any] | None:
    return _fetchone("SELECT id, email, full_name, role FROM profiles WHERE id = ?", (user_id,))


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
    return _fetchall("SELECT id, email, role FROM profiles ORDER BY role, email")


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


def upsert_student(
    student_id: str,
    name: str,
    branch: str,
    batch: str,
    cgpa: float,
    active_backlogs: int,
    resume_text: str,
    parsed_json: str,
    is_placed: bool = False,
    email: str | None = None,
    resume_path: str | None = None,
    created_by: str | None = None,
) -> None:
    _execute(
        """
        INSERT INTO students (
            id, name, email, branch, batch, cgpa, active_backlogs, is_placed,
            resume_text, parsed_json, resume_path, created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            email = excluded.email,
            branch = excluded.branch,
            batch = excluded.batch,
            cgpa = excluded.cgpa,
            active_backlogs = excluded.active_backlogs,
            is_placed = excluded.is_placed,
            resume_text = excluded.resume_text,
            parsed_json = excluded.parsed_json,
            resume_path = COALESCE(excluded.resume_path, students.resume_path),
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
            resume_text,
            _json_param(parsed_json),
            resume_path,
            created_by,
        ),
    )


# ── Reads ───────────────────────────────────────────────────────────────────

def list_policies() -> list[dict]:
    rows = _fetchall("SELECT id, rules_json FROM policies ORDER BY created_at DESC")
    return [{"id": row["id"], **_json_value(row["rules_json"])} for row in rows]


def get_policy(policy_id: str) -> dict | None:
    row = _fetchone("SELECT id, source_text, rules_json FROM policies WHERE id = ?", (policy_id,))
    if row is None:
        return None
    return {"id": row["id"], "source_text": row["source_text"], "rules": _json_value(row["rules_json"])}


def list_jds() -> list[dict]:
    rows = _fetchall("SELECT id, requirements_json, created_by FROM jds ORDER BY created_at DESC")
    return [
        {"id": row["id"], "created_by": _str_or_none(row["created_by"]), **_json_value(row["requirements_json"])}
        for row in rows
    ]


def get_jd(jd_id: str) -> dict | None:
    row = _fetchone(
        "SELECT id, source_text, requirements_json, created_by FROM jds WHERE id = ?", (jd_id,)
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "source_text": row["source_text"],
        "requirements": _json_value(row["requirements_json"]),
        "created_by": _str_or_none(row["created_by"]),
    }


def list_students() -> list[dict]:
    rows = _fetchall(
        "SELECT id, name, email, branch, batch, cgpa, active_backlogs, is_placed "
        "FROM students ORDER BY created_at DESC"
    )
    return [{**row, "is_placed": bool(row["is_placed"])} for row in rows]


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
        "parsed": _json_value(row["parsed_json"]),
        "resume_path": row["resume_path"],
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
    """Bind a timestamp: timestamptz in Postgres, a UTC ISO string in SQLite."""
    value = value.astimezone(UTC)
    return value if using_postgres() else value.isoformat(timespec="seconds")


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
    "j.requirements_json AS jd_requirements, j.created_by AS jd_created_by "
    "FROM applications a JOIN students s ON s.id = a.student_id JOIN jds j ON j.id = a.jd_id"
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
