"""Students applying from their job board (POST /me/jobs/{id}/apply) and CV tips
(POST /me/jobs/{id}/cv-tips)."""
from __future__ import annotations

import pytest

from app import db
from app.schemas import JDRequirements
from app.services import cv_tips as cv_tips_module
from app.services.cv_tips import _RawTip, _RawTips, build_tips
from tests.test_match import _post_jd
from tests.test_my_jobs import CV, board, clock  # noqa: F401  (fixtures)

STUDENT_EMAIL = "riya@uni.edu"


def _login_student(login_as):
    user = login_as("student", email=STUDENT_EMAIL)
    db.upsert_profile(user.id, STUDENT_EMAIL, "student")  # Supabase's sign-up trigger does this
    return user


def _job(client, company):
    return next(j for j in client.get("/me/jobs").json()["jobs"] if j["company"] == company)


# ── Apply ───────────────────────────────────────────────────────────────────

def test_student_applies_and_gets_a_staged_application(client, board, login_as) -> None:
    _login_student(login_as)
    response = client.post(f"/me/jobs/{board['open']}/apply")
    assert response.status_code == 201, response.json()
    app = response.json()
    assert app["status"] == "pending" and app["can_withdraw"] is True
    assert app["source"] == "manual"
    assert app["score"] == 100.0  # Python and FastAPI both evidenced
    assert app["release_at"].startswith("2026-11-21T06:00")  # 24 h withdraw window

    [note] = client.get("/me/notifications").json()
    assert note["message"].startswith("You applied to Acme – SDE")

    acme = _job(client, "Acme")
    assert acme["application"]["status"] == "pending" and acme["application"]["source"] == "manual"


def test_cannot_apply_twice(client, board, login_as) -> None:
    _login_student(login_as)
    client.post(f"/me/jobs/{board['open']}/apply")
    again = client.post(f"/me/jobs/{board['open']}/apply")
    assert again.status_code == 409 and "already have a pending" in again.json()["detail"]


def test_student_can_reapply_after_withdrawing(client, board, login_as, clock) -> None:
    _login_student(login_as)
    first = client.post(f"/me/jobs/{board['open']}/apply").json()
    client.post(f"/applications/{first['id']}/withdraw")

    clock(hours=3)
    response = client.post(f"/me/jobs/{board['open']}/apply")
    assert response.status_code == 201, response.json()
    again = response.json()
    # Same application, back to pending with a fresh snapshot and a new window.
    assert again["id"] == first["id"]
    assert again["status"] == "pending" and again["decided_at"] is None and again["can_withdraw"] is True
    assert again["created_at"] > first["created_at"] and again["release_at"] > first["release_at"]
    assert again["highlights"]

    messages = [n["message"] for n in client.get("/me/notifications").json()]
    assert any(m.startswith("You re-applied to Acme – SDE") for m in messages)
    [listed] = client.get("/me/applications").json()
    assert listed["status"] == "pending"

    # Withdrawing again works, and so does applying again after that.
    assert client.post(f"/applications/{first['id']}/withdraw").status_code == 200
    assert client.post(f"/me/jobs/{board['open']}/apply").status_code == 201


def test_cannot_reapply_once_sent(client, board, login_as, clock) -> None:
    _login_student(login_as)
    client.post(f"/me/jobs/{board['open']}/apply")
    clock(hours=25)  # released to the company
    sent = client.post(f"/me/jobs/{board['open']}/apply")
    assert sent.status_code == 409 and "already have a submitted" in sent.json()["detail"]


def test_cannot_reapply_after_the_deadline(client, board, login_as, clock, monkeypatch) -> None:
    login_as("admin")
    soon = _post_jd(client, monkeypatch, JDRequirements(
        company="Soon", role="Intern", required_skills=["Python"], deadline="2026-11-24"))
    _login_student(login_as)
    app = client.post(f"/me/jobs/{soon}/apply").json()
    client.post(f"/applications/{app['id']}/withdraw")
    clock(days=5)  # past 24 Nov
    late = client.post(f"/me/jobs/{soon}/apply")
    assert late.status_code == 409 and "deadline" in late.json()["detail"]
    assert client.get("/me/applications").json()[0]["status"] == "withdrawn"


def test_auto_apply_never_reapplies_after_withdrawal(client, board, login_as) -> None:
    _login_student(login_as)
    app = client.post(f"/me/jobs/{board['open']}/apply").json()
    client.post(f"/applications/{app['id']}/withdraw")
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 80})
    login_as("officer", email="tpo@uni.edu")
    run = client.post(f"/jds/{board['open']}/auto-apply", params={"policy_id": board["policy"]}).json()
    assert run["created"] == []
    assert "withdrawn" in run["skipped"][0]["reason"]


def test_ineligible_student_is_refused_without_ai_calls(client, board, login_as) -> None:
    _login_student(login_as)
    response = client.post(f"/me/jobs/{board['ece']}/apply")
    assert response.status_code == 409
    assert "not eligible" in response.json()["detail"]
    assert board["llm_calls"] == []
    assert client.get("/me/applications").json() == []


def test_closed_job_is_refused(client, board, login_as) -> None:
    _login_student(login_as)
    response = client.post(f"/me/jobs/{board['closed']}/apply")
    assert response.status_code == 409 and "deadline" in response.json()["detail"]


def test_student_without_cv_is_asked_to_upload_one(client, board, login_as) -> None:
    login_as("admin")
    form = {"name": "Dev Rao", "branch": "CSE", "batch": "2027", "cgpa": "8.0", "active_backlogs": "0", "email": "dev@uni.edu"}
    assert client.post("/students", data=form).status_code in (200, 201)
    login_as("student", email="dev@uni.edu")
    response = client.post(f"/me/jobs/{board['open']}/apply")
    assert response.status_code == 409 and "CV" in response.json()["detail"]


def test_unknown_job_404_and_staff_403(client, board, login_as) -> None:
    _login_student(login_as)
    assert client.post("/me/jobs/nope/apply").status_code == 404
    login_as("officer", email="tpo@uni.edu")
    assert client.post(f"/me/jobs/{board['open']}/apply").status_code == 403
    assert client.post(f"/me/jobs/{board['open']}/cv-tips").status_code == 403


def test_auto_apply_applications_are_marked_auto(client, board, login_as) -> None:
    _login_student(login_as)
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 80})
    officer = login_as("officer", email="tpo@uni.edu")
    db.upsert_profile(officer.id, "tpo@uni.edu", "officer")
    [created] = client.post(f"/jds/{board['open']}/auto-apply", params={"policy_id": board["policy"]}).json()["created"]
    assert created["source"] == "auto"


# ── CV tips ─────────────────────────────────────────────────────────────────

@pytest.fixture
def gap_jd(client, board, monkeypatch, login_as):
    """A JD where the CV misses Docker (required) and Kubernetes (preferred)."""
    login_as("admin")
    jd_id = _post_jd(client, monkeypatch, JDRequirements(
        company="Shipit", role="Backend", required_skills=["Python", "Docker", "SQL"],
        preferred_skills=["Kubernetes"], deadline="2026-12-10"))
    _login_student(login_as)
    return jd_id


@pytest.fixture
def tips_llm(monkeypatch):
    calls = []

    def fake(text, schema, instructions):
        calls.append(instructions)
        return _RawTips(tips=[
            _RawTip(skill="Kubernetes", related_quote="Deployed on k8s clusters", suggestion="Mention the cluster."),
            _RawTip(skill="docker", related_quote="Built services with FastAPI", suggestion="Say you containerised them, if you did."),
            _RawTip(skill="Rust", related_quote=None, suggestion="Not a gap: must be ignored."),
        ])

    monkeypatch.setattr(cv_tips_module, "extract_structured", fake)
    return calls


def test_tips_cover_exactly_the_missing_skills_with_verified_quotes(client, gap_jd, tips_llm) -> None:
    response = client.post(f"/me/jobs/{gap_jd}/cv-tips")
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["source"] == "fresh" and data["score"] is not None
    docker, kube = data["tips"]
    assert docker["skill"] == "Docker" and docker["required"] is True
    assert docker["kind"] == "surface" and docker["related_quote"] == "Built services with FastAPI"
    # The Kubernetes quote isn't in the CV: dropped, and the tip becomes "build".
    assert kube["skill"] == "Kubernetes" and kube["required"] is False
    assert kube["kind"] == "build" and kube["related_quote"] is None
    assert "Docker" in tips_llm[0] and "Kubernetes" in tips_llm[0]


def test_tips_are_cached(client, gap_jd, tips_llm) -> None:
    client.post(f"/me/jobs/{gap_jd}/cv-tips")
    second = client.post(f"/me/jobs/{gap_jd}/cv-tips").json()
    assert second["source"] == "cache" and len(second["tips"]) == 2
    assert len(tips_llm) == 1


def test_nothing_missing_means_no_ai_call(client, board, login_as, tips_llm) -> None:
    _login_student(login_as)
    data = client.post(f"/me/jobs/{board['open']}/cv-tips").json()
    assert data["tips"] == [] and data["source"] == "none"
    assert tips_llm == []


def test_no_tips_when_ineligible(client, board, login_as, tips_llm) -> None:
    _login_student(login_as)
    response = client.post(f"/me/jobs/{board['ece']}/cv-tips")
    assert response.status_code == 409
    assert tips_llm == [] and board["llm_calls"] == []


def test_build_tips_fills_skills_the_llm_skipped() -> None:
    tips = build_tips(_RawTips(tips=[]), ["Go"], [], resume_text=CV.decode())
    [tip] = tips
    assert tip.kind == "build" and "Go" in tip.suggestion


# ── Near the deadline ───────────────────────────────────────────────────────

@pytest.fixture
def due_today(client, board, login_as, monkeypatch):
    """A job closing at the end of 20 Nov IST (18:29:59 UTC); the clock starts 06:00 UTC."""
    login_as("admin")
    jd_id = _post_jd(client, monkeypatch, JDRequirements(
        company="Lastco", role="SRE", required_skills=["Python"], deadline="2026-11-20"))
    _login_student(login_as)
    return jd_id


def test_manual_apply_near_deadline_is_sent_at_last_call(client, due_today, clock) -> None:
    clock(hours=10, minutes=30)  # 16:30 UTC: 2 h left, so "deadline - 6 h" has passed
    response = client.post(f"/me/jobs/{due_today}/apply")
    assert response.status_code == 201, response.json()
    app = response.json()
    assert app["release_at"].startswith("2026-11-20T18:19:59")  # 10 min before the deadline
    assert app["can_withdraw"] is True

    clock(hours=1, minutes=50)  # 18:20 UTC: past the last call, released on read
    [listed] = client.get("/me/applications").json()
    assert listed["status"] == "submitted"


def test_manual_apply_inside_last_call_is_sent_at_once(client, due_today, clock) -> None:
    clock(hours=12, minutes=25)  # 18:25 UTC: 5 min left
    response = client.post(f"/me/jobs/{due_today}/apply")
    assert response.status_code == 201, response.json()
    assert response.json()["release_at"].startswith("2026-11-20T18:25:01")
    clock(seconds=1)
    assert client.get("/me/applications").json()[0]["status"] == "submitted"


def test_manual_apply_accepted_one_second_before_deadline(client, due_today, clock) -> None:
    clock(hours=12, minutes=29, seconds=58)  # 18:29:58 UTC: deadline is 18:29:59
    response = client.post(f"/me/jobs/{due_today}/apply")
    assert response.status_code == 201, response.json()
    assert response.json()["release_at"].startswith("2026-11-20T18:29:59")  # never after the deadline


def test_manual_apply_accepted_in_the_last_second(client, due_today, clock) -> None:
    clock(hours=12, minutes=29, seconds=59, milliseconds=900)  # 23:59:59.9 IST
    response = client.post(f"/me/jobs/{due_today}/apply")
    assert response.status_code == 201, response.json()
    from datetime import UTC, datetime

    release_at = datetime.fromisoformat(response.json()["release_at"])
    assert release_at == datetime(2026, 11, 20, 18, 29, 59, 999999, tzinfo=UTC)  # the deadline, never after


def test_manual_apply_refused_once_the_day_is_over(client, due_today, clock) -> None:
    clock(hours=12, minutes=30)  # 00:00:00 IST on 21 Nov
    response = client.post(f"/me/jobs/{due_today}/apply")
    assert response.status_code == 409 and "has passed" in response.json()["detail"]


def test_auto_apply_still_needs_a_real_withdraw_window(client, due_today, login_as, clock) -> None:
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 80})
    clock(hours=10, minutes=30)
    login_as("officer", email="tpo@uni.edu")
    policy = client.get("/policies").json()[0]["id"]
    response = client.post(f"/jds/{due_today}/auto-apply", params={"policy_id": policy})
    assert response.status_code == 409 and "60 minutes to withdraw" in response.json()["detail"]
