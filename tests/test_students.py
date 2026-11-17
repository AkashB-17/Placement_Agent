from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.db import get_connection
from app.schemas import ParsedResume
from app.services.vectorstore import COLLECTION_RESUMES, get_collection


def _blank_pdf() -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    return buffer.getvalue()


def test_post_student_parses_resume_and_persists(client: TestClient, monkeypatch) -> None:
    parsed = ParsedResume(
        skills=["Python", "FastAPI"],
        projects=["Campus portal"],
        education=["B.Tech CSE"],
        experience=[],
    )
    monkeypatch.setattr(
        "app.routers.students.text_from_upload",
        lambda filename, data: "Python FastAPI. Project: Campus portal. Education: B.Tech CSE.",
    )
    monkeypatch.setattr(
        "app.routers.students.extract_structured",
        lambda text, schema, instructions: parsed,
    )

    response = client.post(
        "/students",
        data={
            "name": "Ada Lovelace",
            "branch": "Computer Science & Engineering",
            "batch": "2022-2026",
            "cgpa": "9.1",
            "active_backlogs": "0",
        },
        files={"resume": ("resume.pdf", _blank_pdf(), "application/pdf")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["parsed_resume"]["skills"] == ["Python", "FastAPI"]
    assert payload["profile"]["name"] == "Ada Lovelace"
    assert payload["profile"]["branch"] == "CSE"
    assert payload["profile"]["batch"] == "2026"
    assert payload["profile"]["is_placed"] is False

    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM students").fetchone()
        assert row["n"] == 1
    finally:
        conn.close()

    # Resumes are scored from full text and deliberately not embedded, so no student
    # data ends up in the local vector store.
    assert get_collection(COLLECTION_RESUMES).count() == 0
