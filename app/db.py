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
import weakref
from collections.abc import Iterator
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
