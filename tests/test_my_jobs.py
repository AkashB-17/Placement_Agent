"""GET /me/jobs: the student job board. Deterministic, no LLM calls."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.schemas import JDRequirements, ParsedResume, PolicyRules
from app.services import auto_apply, scoring
from tests.test_match import _evidence_from_resume, _post_jd, _post_policy

START = datetime(2026, 11, 20, 6, 0, tzinfo=UTC)
CV = b"Riya Sen. Python developer. Built services with FastAPI. Wrote SQL."


@pytest.fixture
def clock(monkeypatch):
    now = {"t": START}
    monkeypatch.setattr(auto_apply, "utcnow", lambda: now["t"])

    def advance(**delta):
        now["t"] += timedelta(**delta)

    return advance


@pytest.fixture
def board(client: TestClient, monkeypatch, login_as, clock):
    """A policy, three JDs (open, ECE-only, closed) and a linked CSE student with a CV."""
    llm_calls = []

    def counting(text, schema, instructions):
        llm_calls.append(text)
        return _evidence_from_resume(text, schema, instructions)

    monkeypatch.setattr(scoring, "extract_structured", counting)
    monkeypatch.setattr("app.services.matching.retrieve", lambda *a, **k: [])
    monkeypatch.setattr("app.routers.students.extract_structured", lambda *a: ParsedResume(skills=["Python"]))
    ids = {
        "policy": _post_policy(client, monkeypatch, PolicyRules(min_cgpa=7.0)),
        "open": _post_jd(client, monkeypatch, JDRequirements(
            company="Acme", role="SDE", ctc="10 LPA", required_skills=["Python", "FastAPI"], deadline="2026-12-05")),
        "ece": _post_jd(client, monkeypatch, JDRequirements(
            company="Volt", role="Firmware", required_skills=["Embedded C"], allowed_branches=["ECE"])),
        "closed": _post_jd(client, monkeypatch, JDRequirements(
            company="Oldco", role="Analyst", required_skills=["SQL"], deadline="November 15, 2026")),
    }
    form = {"name": "Riya Sen", "branch": "CSE", "batch": "2027", "cgpa": "8.6", "active_backlogs": "0", "email": "riya@uni.edu"}
    client.post("/students", data=form, files={"resume": ("cv.txt", CV, "text/plain")})
    login_as("student", email="riya@uni.edu")
    return {**ids, "llm_calls": llm_calls}


def _jobs(client):
    response = client.get("/me/jobs")
    assert response.status_code == 200, response.json()
    return response.json()


def test_board_lists_every_job_with_eligibility_and_deadline(client, board) -> None:
    data = _jobs(client)
    assert data["policy_id"] == board["policy"]
    jobs = {j["company"]: j for j in data["jobs"]}
    assert set(jobs) == {"Acme", "Volt", "Oldco"}

    acme = jobs["Acme"]
    assert acme["eligibility"]["eligible"] is True
    assert acme["ctc"] == "10 LPA" and acme["closed"] is False
    assert acme["deadline_at"].startswith("2026-12-05T18:29:59")  # 23:59:59 IST
    assert acme["application"] is None and acme["posted_at"]

    volt = jobs["Volt"]
    assert volt["eligibility"]["eligible"] is False
    [rule] = volt["eligibility"]["failed_rules"]
    assert rule["rule"] == "allowed_branches" and rule["source"] == "jd"

    assert jobs["Oldco"]["closed"] is True


def test_board_makes_no_ai_calls(client, board) -> None:
    _jobs(client)
    assert board["llm_calls"] == []


def test_application_status_appears_after_auto_apply(client, board, login_as, clock) -> None:
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 80})
    login_as("officer", email="tpo@uni.edu")
    run = client.post(f"/jds/{board['open']}/auto-apply", params={"policy_id": board["policy"]}).json()
    assert len(run["created"]) == 1

    login_as("student", email="riya@uni.edu")
    acme = next(j for j in _jobs(client)["jobs"] if j["company"] == "Acme")
    assert acme["application"]["status"] == "pending"
    assert acme["application"]["can_withdraw"] is True

    clock(hours=25)  # past the withdraw window: released on read
    acme = next(j for j in _jobs(client)["jobs"] if j["company"] == "Acme")
    assert acme["application"]["status"] == "submitted"
    assert acme["application"]["can_withdraw"] is False


def test_explicit_policy_and_unknown_policy(client, board, login_as, monkeypatch) -> None:
    login_as("officer", email="tpo@uni.edu")
    strict = _post_policy(client, monkeypatch, PolicyRules(min_cgpa=9.0))
    login_as("student", email="riya@uni.edu")
    data = client.get("/me/jobs", params={"policy_id": strict}).json()
    acme = next(j for j in data["jobs"] if j["company"] == "Acme")
    assert acme["eligibility"]["failed_rules"][0]["rule"] == "min_cgpa"
    assert client.get("/me/jobs", params={"policy_id": "nope"}).status_code == 404


def test_unlinked_student_gets_404(client, board, login_as) -> None:
    login_as("student", email="stranger@uni.edu")
    assert client.get("/me/jobs").status_code == 404


@pytest.mark.parametrize("role", ["officer", "recruiter", "admin"])
def test_board_is_student_only(client, board, login_as, role) -> None:
    login_as(role, email=f"{role}@uni.edu")
    assert client.get("/me/jobs").status_code == 403
