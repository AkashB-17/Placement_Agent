from fastapi.testclient import TestClient

from app.db import get_connection
from app.schemas import JDRequirements
from app.services.vectorstore import COLLECTION_JDS, get_collection


def test_post_jd_extracts_requirements_and_persists(client: TestClient, monkeypatch) -> None:
    requirements = JDRequirements(
        company="Acme",
        role="SDE Intern",
        required_skills=["Python"],
        preferred_skills=["SQL"],
        min_cgpa_override=None,
        allowed_branches=["CSE"],
        ctc="12 LPA",
        deadline="2026-11-01",
        experience_required=None,
    )
    monkeypatch.setattr(
        "app.routers.jds.extract_structured",
        lambda text, schema, instructions: requirements,
    )

    jd_text = "Acme is hiring SDE Interns. Required: Python. Preferred: SQL. CSE. CTC 12 LPA. Deadline 2026-11-01."
    response = client.post("/jds", data={"text": jd_text})
    assert response.status_code == 200
    payload = response.json()
    assert payload["requirements"]["company"] == "Acme"
    assert payload["requirements"]["required_skills"] == ["Python"]
    assert payload["requirements"]["experience_required"] is None

    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM jds").fetchone()
        assert row["n"] == 1
    finally:
        conn.close()

    assert get_collection(COLLECTION_JDS).count() >= 1
