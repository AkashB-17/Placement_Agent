import hashlib
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
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO students (
                id, name, branch, batch, cgpa, active_backlogs, resume_text, parsed_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                branch = excluded.branch,
                batch = excluded.batch,
                cgpa = excluded.cgpa,
                active_backlogs = excluded.active_backlogs,
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
                resume_text,
                parsed_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()
