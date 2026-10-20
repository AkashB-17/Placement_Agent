"""POST /match and GET /jds/{jd_id}/ranked. LLM and retrieval mocked."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.schemas import JDRequirements, ParsedResume, PolicyRules
from app.services import scoring
from app.services.scoring import EvidenceReport, SkillEvidence

RESUMES = {
    "strong": "Python developer. Built services with FastAPI and wrote SQL daily.",
    "partial": "Python scripting for data cleanup.",
    "none": "Mechanical design using SolidWorks.",
}


def _post_policy(client, monkeypatch, rules: PolicyRules) -> str:
    monkeypatch.setattr("app.routers.policies.extract_structured", lambda *a: rules)
    return client.post("/policies", data={"text": f"policy {rules.model_dump_json()}"}).json()["id"]


def _post_jd(client, monkeypatch, jd: JDRequirements) -> str:
    monkeypatch.setattr("app.routers.jds.extract_structured", lambda *a: jd)
    return client.post("/jds", data={"text": f"jd {jd.model_dump_json()}"}).json()["id"]


def _post_student(client, monkeypatch, name, resume="strong", **fields) -> str:
    monkeypatch.setattr("app.routers.students.extract_structured", lambda *a: ParsedResume())
    form = {"name": name, "branch": "CSE", "batch": "2026", "cgpa": "8.5", "active_backlogs": "0"}
    form.update({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in fields.items()})
    response = client.post(
        "/students", data=form, files={"resume": ("resume.txt", RESUMES[resume].encode(), "text/plain")}
    )
    assert response.status_code == 200, response.json()
    return response.json()["id"]


def _evidence_from_resume(text, schema, instructions):
    """Fake LLM: claims a skill when the skill name literally appears in the resume."""
    skills = instructions.split("Skills: ")[1].strip("[]").replace("'", "").split(", ")
    items = []
    for skill in skills:
        start = text.lower().find(skill.lower())
        quote = text[start : start + len(skill)] if start >= 0 else None
        items.append(SkillEvidence(skill=skill, evidenced=quote is not None, evidence_quote=quote))
    return EvidenceReport(skills=items)


@pytest.fixture
def retrieval_log(monkeypatch):
    calls = []

    def _fake_retrieve(collection, query, k, where=None):
        calls.append({"collection": collection, "query": query, "k": k, "where": where})
        return [{"text": f"[{collection}] clause about {query}", "metadata": {}, "distance": 0.1}]

    monkeypatch.setattr("app.routers.match.retrieve", _fake_retrieve)
    monkeypatch.setattr(scoring, "extract_structured", _evidence_from_resume)
    return calls


JD = JDRequirements(company="Acme", role="SDE", required_skills=["Python", "FastAPI"], preferred_skills=["SQL"])


# ── /match ───────────────────────────────────────────────────────────────────

def test_match_eligible_student_is_scored(client: TestClient, monkeypatch, retrieval_log) -> None:
    policy_id = _post_policy(client, monkeypatch, PolicyRules(min_cgpa=7.0))
    jd_id = _post_jd(client, monkeypatch, JD)
    student_id = _post_student(client, monkeypatch, "Alice")

    data = client.post("/match", json={"jd_id": jd_id, "student_id": student_id, "policy_id": policy_id}).json()
    assert data["eligibility"]["eligible"] is True
    assert data["score_breakdown"]["score"] == 100.0
    assert data["score_breakdown"]["matched_required"] == ["Python", "FastAPI"]
    assert data["auto_apply_recommended"] is True
    assert data["citations"] == []
    assert retrieval_log == []


def test_match_ineligible_skips_scoring_and_cites_policy(client: TestClient, monkeypatch, retrieval_log) -> None:
    monkeypatch.setattr(scoring, "extract_structured", lambda *a: pytest.fail("must not score"))
    policy_id = _post_policy(client, monkeypatch, PolicyRules(min_cgpa=7.0, max_active_backlogs=0))
    jd_id = _post_jd(client, monkeypatch, JD)
    student_id = _post_student(client, monkeypatch, "Bob", active_backlogs=1)

    data = client.post("/match", json={"jd_id": jd_id, "student_id": student_id, "policy_id": policy_id}).json()
    assert data["eligibility"]["eligible"] is False
    assert data["score_breakdown"] is None
    assert data["auto_apply_recommended"] is False
    [citation] = data["citations"]
    assert citation["rule"] == "max_active_backlogs"
    assert citation["source"] == "policy"
    assert citation["chunks"][0]["text"].startswith("[policies]")
    assert retrieval_log[0]["where"] == {"doc_id": policy_id}
    assert retrieval_log[0]["k"] == 2
    assert "backlogs" in retrieval_log[0]["query"]  # natural-language query, not a rule id


def test_jd_origin_failure_cites_the_jd(client: TestClient, monkeypatch, retrieval_log) -> None:
    policy_id = _post_policy(client, monkeypatch, PolicyRules(min_cgpa=6.0))
    jd_id = _post_jd(client, monkeypatch, JD.model_copy(update={"min_cgpa_override": 9.0}))
    student_id = _post_student(client, monkeypatch, "Cara", cgpa=8.0)

    data = client.post("/match", json={"jd_id": jd_id, "student_id": student_id, "policy_id": policy_id}).json()
    [citation] = data["citations"]
    assert (citation["rule"], citation["source"], citation["source_id"]) == ("min_cgpa", "jd", jd_id)
    assert retrieval_log[0]["collection"] == "jds"
    assert retrieval_log[0]["where"] == {"doc_id": jd_id}


def test_below_threshold_not_recommended(client: TestClient, monkeypatch, retrieval_log) -> None:
    policy_id = _post_policy(client, monkeypatch, PolicyRules())
    jd_id = _post_jd(client, monkeypatch, JD)
    student_id = _post_student(client, monkeypatch, "Dev", resume="partial")

    data = client.post("/match", json={"jd_id": jd_id, "student_id": student_id, "policy_id": policy_id}).json()
    assert data["score_breakdown"]["score"] == pytest.approx(37.5)  # 0.75 * 1/2
    assert data["auto_apply_recommended"] is False


@pytest.mark.parametrize("missing", ["jd_id", "student_id", "policy_id"])
def test_match_unknown_id_is_404(client: TestClient, monkeypatch, retrieval_log, missing) -> None:
    ids = {
        "policy_id": _post_policy(client, monkeypatch, PolicyRules()),
        "jd_id": _post_jd(client, monkeypatch, JD),
        "student_id": _post_student(client, monkeypatch, "Eve"),
    }
    ids[missing] = "does-not-exist"
    assert client.post("/match", json=ids).status_code == 404


def test_match_bad_body_is_422(client: TestClient) -> None:
    assert client.post("/match", json={"jd_id": "x"}).status_code == 422


# ── /ranked ──────────────────────────────────────────────────────────────────

def test_ranked_orders_eligible_and_explains_ineligible(client: TestClient, monkeypatch, retrieval_log) -> None:
    policy_id = _post_policy(client, monkeypatch, PolicyRules(min_cgpa=7.0, max_active_backlogs=0))
    jd_id = _post_jd(client, monkeypatch, JD)
    none_id = _post_student(client, monkeypatch, "Zed", resume="none")
    partial_id = _post_student(client, monkeypatch, "Yan", resume="partial")
    strong_id = _post_student(client, monkeypatch, "Xia", resume="strong")
    # The two demo edge cases: perfect skills but ineligible.
    backlog_id = _post_student(client, monkeypatch, "Wes", active_backlogs=1)
    low_cgpa_id = _post_student(client, monkeypatch, "Val", cgpa=6.5)

    response = client.get(f"/jds/{jd_id}/ranked", params={"policy_id": policy_id})
    assert response.status_code == 200
    data = response.json()

    assert [r["student_id"] for r in data["eligible"]] == [strong_id, partial_id, none_id]
    scores = [r["score_breakdown"]["score"] for r in data["eligible"]]
    assert scores == sorted(scores, reverse=True)
    assert data["auto_apply_threshold"] == 80.0

    ineligible = {r["student_id"]: r for r in data["ineligible"]}
    assert set(ineligible) == {backlog_id, low_cgpa_id}
    assert [f["rule"] for f in ineligible[backlog_id]["eligibility"]["failed_rules"]] == ["max_active_backlogs"]
    assert [f["rule"] for f in ineligible[low_cgpa_id]["eligibility"]["failed_rules"]] == ["min_cgpa"]
    for entry in ineligible.values():
        assert entry["score_breakdown"] is None
        assert entry["citations"] and entry["citations"][0]["chunks"]


def test_ranked_unknown_jd_or_policy_is_404(client: TestClient, monkeypatch) -> None:
    policy_id = _post_policy(client, monkeypatch, PolicyRules())
    jd_id = _post_jd(client, monkeypatch, JD)
    assert client.get("/jds/nope/ranked", params={"policy_id": policy_id}).status_code == 404
    assert client.get(f"/jds/{jd_id}/ranked", params={"policy_id": "nope"}).status_code == 404


def test_ranked_requires_policy_id(client: TestClient, monkeypatch) -> None:
    jd_id = _post_jd(client, monkeypatch, JD)
    assert client.get(f"/jds/{jd_id}/ranked").status_code == 422
