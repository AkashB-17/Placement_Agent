"""Staged auto-apply: opt-in, run, withdraw window, release, deadline buffer, roles.

LLM and retrieval are mocked; time is a fake clock moved by the tests."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db
from app.schemas import JDRequirements, PolicyRules
from app.services import auto_apply, scoring
from tests.test_match import RESUMES, _evidence_from_resume, _post_jd, _post_policy, _post_student

START = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)  # 11:30 IST


@pytest.fixture
def clock(monkeypatch):
    now = {"t": START}
    monkeypatch.setattr(auto_apply, "utcnow", lambda: now["t"])

    def advance(**delta):
        now["t"] += timedelta(**delta)

    advance.now = lambda: now["t"]
    return advance


@pytest.fixture
def world(client: TestClient, monkeypatch, clock):
    """As admin: a policy, a JD (no deadline) and four students. Scores: alice 100, bob 37.5."""
    monkeypatch.setattr("app.services.matching.retrieve", lambda *a, **k: [])
    monkeypatch.setattr(scoring, "extract_structured", _evidence_from_resume)
    jd = JDRequirements(company="Acme", role="SDE", required_skills=["Python", "FastAPI"], preferred_skills=["SQL"])
    return {
        "policy": _post_policy(client, monkeypatch, PolicyRules(min_cgpa=7.0, max_active_backlogs=0)),
        "jd": _post_jd(client, monkeypatch, jd),
        "alice": _post_student(client, monkeypatch, "Alice", "strong", email="alice@uni.edu"),
        "bob": _post_student(client, monkeypatch, "Bob", "partial", email="bob@uni.edu"),
        "carol": _post_student(client, monkeypatch, "Carol", "strong", email="carol@uni.edu", active_backlogs=2),
        "dave": _post_student(client, monkeypatch, "Dave", "strong", email="dave@uni.edu"),
    }


def _opt_in(client, login_as, email, **prefs):
    login_as("student", email=email)
    body = {"enabled": True, "min_score": 80, "excluded_companies": [], **prefs}
    response = client.put("/me/auto-apply", json=body)
    assert response.status_code == 200, response.json()
    return response.json()


def _run(client, login_as, world, jd_key="jd"):
    login_as("officer", email="officer@uni.edu")
    return client.post(f"/jds/{world[jd_key]}/auto-apply", params={"policy_id": world["policy"]})


# ── Preferences ──────────────────────────────────────────────────────────────

def test_preferences_default_off_and_validated(client, world, login_as) -> None:
    login_as("student", email="alice@uni.edu")
    prefs = client.get("/me/auto-apply").json()
    assert prefs["enabled"] is False
    assert prefs["min_score"] == prefs["threshold"] == 80

    below = client.put("/me/auto-apply", json={"enabled": True, "min_score": 70})
    assert below.status_code == 422

    saved = client.put(
        "/me/auto-apply", json={"enabled": True, "min_score": 90, "excluded_companies": [" Acme ", "acme", "Globex"]}
    ).json()
    assert saved["enabled"] is True and saved["min_score"] == 90
    assert saved["excluded_companies"] == ["Acme", "Globex"]


def test_unlinked_student_gets_404(client, world, login_as) -> None:
    login_as("student", email="nobody@uni.edu")
    assert client.get("/me/auto-apply").status_code == 404
    assert client.get("/me/applications").status_code == 404


# ── Run ──────────────────────────────────────────────────────────────────────

def test_run_applies_only_opted_in_qualifying_students(client, world, login_as, clock) -> None:
    for email in ("alice@uni.edu", "bob@uni.edu", "carol@uni.edu"):
        _opt_in(client, login_as, email)  # dave never opts in

    run = _run(client, login_as, world)
    assert run.status_code == 200, run.json()
    data = run.json()

    [created] = data["created"]
    assert created["student_name"] == "Alice"
    assert created["status"] == "pending" and created["can_withdraw"] is True
    assert created["score"] == 100.0
    assert created["score_breakdown"]["matched_required"] == ["Python", "FastAPI"]
    assert datetime.fromisoformat(created["release_at"]) == START + timedelta(hours=24)

    reasons = {s["student_name"]: s["reason"] for s in data["skipped"]}
    assert "below their bar of 80" in reasons["Bob"]
    assert reasons["Carol"].startswith("Not eligible")
    assert "Dave" not in reasons
    assert data["not_opted_in"] == 1


def test_application_pins_resume_and_notifies(client, world, login_as) -> None:
    _opt_in(client, login_as, "alice@uni.edu")
    [created] = _run(client, login_as, world).json()["created"]

    stored = db.get_application(created["id"])
    assert stored["resume_sha"] == hashlib.sha256(RESUMES["strong"].encode()).hexdigest()

    login_as("student", email="alice@uni.edu")
    [note] = client.get("/me/notifications").json()
    assert note["kind"] == "application_pending" and not note["read"]
    assert "Acme" in note["message"] and "Withdraw before" in note["message"]
    assert client.post("/me/notifications/read").status_code == 204
    assert client.get("/me/notifications").json()[0]["read"] is True


def test_student_bar_and_excluded_company_respected(client, world, login_as) -> None:
    _opt_in(client, login_as, "alice@uni.edu", excluded_companies=["ACME"])
    _opt_in(client, login_as, "dave@uni.edu", min_score=100)
    data = _run(client, login_as, world).json()
    assert data["created"][0]["student_name"] == "Dave"  # 100 >= 100
    assert "Excluded this company" in {s["student_name"]: s["reason"] for s in data["skipped"]}["Alice"]


def test_policy_application_limit(client, world, login_as, monkeypatch) -> None:
    world["policy"] = _post_policy(client, monkeypatch, PolicyRules(max_applications_per_student=1))
    second_jd = _post_jd(client, monkeypatch, JDRequirements(company="Globex", required_skills=["Python"]))
    _opt_in(client, login_as, "alice@uni.edu")
    assert len(_run(client, login_as, world).json()["created"]) == 1

    world["jd2"] = second_jd
    data = _run(client, login_as, world, jd_key="jd2").json()
    assert data["created"] == []
    assert "policy limit of 1" in data["skipped"][0]["reason"]


# ── Withdraw window and release ──────────────────────────────────────────────

def test_withdraw_inside_window_is_final(client, world, login_as, clock) -> None:
    _opt_in(client, login_as, "alice@uni.edu")
    [created] = _run(client, login_as, world).json()["created"]

    clock(hours=23)
    login_as("student", email="alice@uni.edu")
    withdrawn = client.post(f"/applications/{created['id']}/withdraw")
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn" and withdrawn.json()["can_withdraw"] is False
    assert client.post(f"/applications/{created['id']}/withdraw").status_code == 409

    clock(hours=2)  # past the original release time: a withdrawn application stays withdrawn
    assert client.get("/me/applications").json()[0]["status"] == "withdrawn"

    rerun = _run(client, login_as, world).json()
    assert rerun["created"] == []
    assert "withdrawn application" in rerun["skipped"][0]["reason"]


def test_release_after_window_then_withdraw_refused(client, world, login_as, clock) -> None:
    _opt_in(client, login_as, "alice@uni.edu")
    [created] = _run(client, login_as, world).json()["created"]

    clock(hours=24, seconds=1)
    login_as("student", email="alice@uni.edu")
    [mine] = client.get("/me/applications").json()
    assert mine["status"] == "submitted" and mine["can_withdraw"] is False
    assert mine["decided_at"] is not None

    response = client.post(f"/applications/{created['id']}/withdraw")
    assert response.status_code == 409
    assert "already been sent" in response.json()["detail"]
    kinds = [n["kind"] for n in client.get("/me/notifications").json()]
    assert kinds.count("application_submitted") == 1


def test_release_is_idempotent(client, world, login_as, clock) -> None:
    _opt_in(client, login_as, "alice@uni.edu")
    _run(client, login_as, world)
    clock(hours=25)
    assert len(auto_apply.release_due()) == 1
    assert auto_apply.release_due() == []


def test_student_cannot_withdraw_someone_elses(client, world, login_as) -> None:
    _opt_in(client, login_as, "alice@uni.edu")
    [created] = _run(client, login_as, world).json()["created"]
    login_as("student", email="dave@uni.edu")
    assert client.post(f"/applications/{created['id']}/withdraw").status_code == 404


# ── Deadline ─────────────────────────────────────────────────────────────────

def _jd_with_deadline(client, monkeypatch, deadline):
    jd = JDRequirements(company="Initech", required_skills=["Python"], deadline=deadline)
    return _post_jd(client, monkeypatch, jd)


def test_deadline_buffer_pulls_release_earlier(client, world, login_as, monkeypatch) -> None:
    # Deadline 17 Nov 23:59:59.999999 IST = 18:29:59.999999 UTC; minus 6 h buffer = 12:29:59.999999 UTC (< 24 h window).
    world["jd_soon"] = _jd_with_deadline(client, monkeypatch, "November 17, 2026")
    _opt_in(client, login_as, "alice@uni.edu")
    data = _run(client, login_as, world, jd_key="jd_soon").json()
    expected = datetime(2026, 11, 17, 12, 29, 59, 999999, tzinfo=UTC)
    assert datetime.fromisoformat(data["release_cutoff"]) == expected
    assert datetime.fromisoformat(data["created"][0]["release_at"]) == expected


def test_run_refused_when_too_close_to_deadline(client, world, login_as, monkeypatch, clock) -> None:
    world["jd_soon"] = _jd_with_deadline(client, monkeypatch, "2026-11-17")
    clock(hours=6)  # 12:00 UTC: 30 minutes before the cutoff
    _opt_in(client, login_as, "alice@uni.edu")
    response = _run(client, login_as, world, jd_key="jd_soon")
    assert response.status_code == 409
    assert "Too close to the application deadline" in response.json()["detail"]
    assert db.list_applications() == []


def test_run_refused_after_deadline(client, world, login_as, monkeypatch) -> None:
    world["jd_past"] = _jd_with_deadline(client, monkeypatch, "15th November 2026")
    response = _run(client, login_as, world, jd_key="jd_past")
    assert response.status_code == 409
    assert "has passed" in response.json()["detail"]


@pytest.mark.parametrize(
    ("text", "expected_utc"),
    [
        ("November 20, 2026", datetime(2026, 11, 20, 18, 29, 59, 999999, tzinfo=UTC)),
        ("20th Nov 2026.", datetime(2026, 11, 20, 18, 29, 59, 999999, tzinfo=UTC)),
        ("Friday, 20 November 2026", datetime(2026, 11, 20, 18, 29, 59, 999999, tzinfo=UTC)),
        ("2026-11-20", datetime(2026, 11, 20, 18, 29, 59, 999999, tzinfo=UTC)),
        ("20/11/2026", datetime(2026, 11, 20, 18, 29, 59, 999999, tzinfo=UTC)),
        ("2026-11-20T10:00:00+00:00", datetime(2026, 11, 20, 10, 0, tzinfo=UTC)),
    ],
)
def test_parse_deadline(client, text, expected_utc) -> None:
    assert auto_apply.parse_deadline(text) == expected_utc


@pytest.mark.parametrize("text", [None, "", "rolling basis", "ASAP", "end of month"])
def test_unparseable_deadline_is_none(client, text) -> None:
    assert auto_apply.parse_deadline(text) is None


# ── Roles ────────────────────────────────────────────────────────────────────

def test_only_staff_can_run(client, world, login_as) -> None:
    for role in ("student", "recruiter"):
        login_as(role, email=f"{role}@uni.edu")
        response = client.post(f"/jds/{world['jd']}/auto-apply", params={"policy_id": world["policy"]})
        assert response.status_code == 403


def test_recruiter_sees_only_released_applications_for_own_jds(client, world, login_as, monkeypatch, clock) -> None:
    owner = login_as("recruiter", email="hr@acme.com")
    jd = JDRequirements(company="Acme", role="Backend", required_skills=["Python"])
    world["jd_r"] = _post_jd(client, monkeypatch, jd)
    _opt_in(client, login_as, "alice@uni.edu")
    [created] = _run(client, login_as, world, jd_key="jd_r").json()["created"]

    login_as("recruiter", email="hr@acme.com", user_id=owner.id)
    assert client.get("/applications").json() == []  # still pending: not sent
    assert client.get("/applications", params={"status": "pending"}).json() == []
    assert client.get(f"/applications/{created['id']}/resume").status_code == 404

    clock(hours=25)
    [visible] = client.get("/applications").json()
    assert visible["id"] == created["id"] and visible["status"] == "submitted"

    login_as("recruiter", email="hr@globex.com")  # a different recruiter
    assert client.get("/applications").json() == []


def test_staff_list_filters_by_jd_and_status(client, world, login_as) -> None:
    _opt_in(client, login_as, "alice@uni.edu")
    _run(client, login_as, world)
    login_as("officer", email="officer@uni.edu")
    assert len(client.get("/applications", params={"jd_id": world["jd"], "status": "pending"}).json()) == 1
    assert client.get("/applications", params={"status": "submitted"}).json() == []
