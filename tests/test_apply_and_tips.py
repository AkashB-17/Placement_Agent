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


def test_cannot_apply_twice_or_after_withdrawing(client, board, login_as) -> None:
    _login_student(login_as)
    app = client.post(f"/me/jobs/{board['open']}/apply").json()
    again = client.post(f"/me/jobs/{board['open']}/apply")
    assert again.status_code == 409 and "already have a pending" in again.json()["detail"]

    client.post(f"/applications/{app['id']}/withdraw")
    after = client.post(f"/me/jobs/{board['open']}/apply")
    assert after.status_code == 409 and "final" in after.json()["detail"]


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
