from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db import get_connection
from app.schemas import PolicyRules
from app.services.vectorstore import COLLECTION_POLICIES, get_collection


def test_post_policy_extracts_rules_and_persists(client: TestClient, monkeypatch) -> None:
    rules = PolicyRules(
        min_cgpa=7.0,
        max_active_backlogs=1,
        allowed_branches=["CSE", "ECE"],
        allowed_batches=["2026"],
        max_applications_per_student=5,
        placed_student_rules=["Placed students may sit for 2x CTC roles only."],
    )
    monkeypatch.setattr(
        "app.routers.policies.extract_structured",
        lambda text, schema, instructions: rules,
    )

    policy_text = (
        "Minimum CGPA is 7.0. Max one active backlog. CSE and ECE of 2026. "
        "At most 5 applications. Placed students may sit for 2x CTC roles only."
    )
    response = client.post("/policies", data={"text": policy_text})
    assert response.status_code == 200
    payload = response.json()
    assert payload["rules"]["min_cgpa"] == 7.0
    assert payload["rules"]["allowed_branches"] == ["CSE", "ECE"]

    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM policies").fetchone()
        assert row["n"] == 1
    finally:
        conn.close()

    count_after_first = get_collection(COLLECTION_POLICIES).count()
    assert count_after_first >= 1

    again = client.post("/policies", data={"text": policy_text})
    assert again.status_code == 200
    assert again.json()["id"] == payload["id"]
    assert get_collection(COLLECTION_POLICIES).count() == count_after_first


def test_post_policy_returns_422_when_llm_validation_fails(client: TestClient, monkeypatch) -> None:
    def fail(_text, _schema, _instructions):
        raise HTTPException(status_code=422, detail="LLM output failed schema validation")

    monkeypatch.setattr("app.routers.policies.extract_structured", fail)
    response = client.post("/policies", data={"text": "No numeric CGPA is stated anywhere."})
    assert response.status_code == 422
