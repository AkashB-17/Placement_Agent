import hashlib
import json
import sqlite3
from pathlib import Path

from app.config import get_settings

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS policies (
    id TEXT PRIMARY KEY,
    source_text TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jds (
    id TEXT PRIMARY KEY,
    source_text TEXT NOT NULL,
    requirements_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    branch TEXT NOT NULL,
    batch TEXT NOT NULL,
    cgpa REAL NOT NULL,
    active_backlogs INTEGER NOT NULL,
    is_placed INTEGER NOT NULL DEFAULT 0,
    resume_text TEXT,
    parsed_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def make_document_id(*parts: str) -> str:
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def get_connection() -> sqlite3.Connection:
    return _connect(Path(get_settings().sqlite_path))


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        # Idempotent migration for existing DBs
        try:
            conn.execute("ALTER TABLE students ADD COLUMN is_placed INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()
    finally:
        conn.close()


def upsert_policy(policy_id: str, source_text: str, rules_json: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO policies (id, source_text, rules_json)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_text = excluded.source_text,
                rules_json = excluded.rules_json
            """,
            (policy_id, source_text, rules_json),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_jd(jd_id: str, source_text: str, requirements_json: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO jds (id, source_text, requirements_json)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_text = excluded.source_text,
                requirements_json = excluded.requirements_json
            """,
            (jd_id, source_text, requirements_json),
        )
        conn.commit()
    finally:
        conn.close()


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
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO students (
                id, name, branch, batch, cgpa, active_backlogs, is_placed, resume_text, parsed_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                branch = excluded.branch,
                batch = excluded.batch,
                cgpa = excluded.cgpa,
                active_backlogs = excluded.active_backlogs,
                is_placed = excluded.is_placed,
                resume_text = excluded.resume_text,
                parsed_json = excluded.parsed_json
            """,
            (
                student_id,
                name,
                branch,
                batch,
                cgpa,
                active_backlogs,
                int(is_placed),
                resume_text,
                parsed_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ── Read helpers ────────────────────────────────────────────────────────────

def list_policies() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, rules_json FROM policies ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            rules = json.loads(row["rules_json"])
            result.append({"id": row["id"], **rules})
        return result
    finally:
        conn.close()


def get_policy(policy_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, source_text, rules_json FROM policies WHERE id = ?", (policy_id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "source_text": row["source_text"], "rules": json.loads(row["rules_json"])}
    finally:
        conn.close()


def list_jds() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, requirements_json FROM jds ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            req = json.loads(row["requirements_json"])
            result.append({"id": row["id"], **req})
        return result
    finally:
        conn.close()


def get_jd(jd_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, source_text, requirements_json FROM jds WHERE id = ?", (jd_id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "source_text": row["source_text"], "requirements": json.loads(row["requirements_json"])}
    finally:
        conn.close()


def list_students() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, branch, batch, cgpa, active_backlogs, is_placed FROM students ORDER BY created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_student(student_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, branch, batch, cgpa, active_backlogs, is_placed, resume_text, parsed_json FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "branch": row["branch"],
            "batch": row["batch"],
            "cgpa": row["cgpa"],
            "active_backlogs": row["active_backlogs"],
            "is_placed": bool(row["is_placed"]),
            "resume_text": row["resume_text"] or "",
            "parsed": json.loads(row["parsed_json"]),
        }
    finally:
        conn.close()


def get_all_students() -> list[dict]:
    """Return all students with full data for ranking."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, branch, batch, cgpa, active_backlogs, is_placed, resume_text, parsed_json FROM students"
        ).fetchall()
        result = []
        for row in rows:
            result.append({
                "id": row["id"],
                "name": row["name"],
                "branch": row["branch"],
                "batch": row["batch"],
                "cgpa": row["cgpa"],
                "active_backlogs": row["active_backlogs"],
                "is_placed": bool(row["is_placed"]),
                "resume_text": row["resume_text"] or "",
                "parsed": json.loads(row["parsed_json"]),
            })
        return result
    finally:
        conn.close()
