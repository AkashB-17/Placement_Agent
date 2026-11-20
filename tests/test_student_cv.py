"""Students upload their own CV; the office owns the academic record."""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from app import db
from app.schemas import JDRequirements, ParsedResume, PolicyRules
from app.services import scoring
from tests.test_match import _evidence_from_resume, _post_jd, _post_policy

ACADEMIC = {"name": "Riya Sen", "branch": "CSE", "batch": "2027", "cgpa": "8.6", "active_backlogs": "0", "email": "riya@uni.edu"}
CV_V1 = b"Riya Sen. Built REST services in Python with FastAPI. Wrote SQL reports."
CV_V2 = b"Riya Sen. Python and FastAPI developer. Docker deployments. SQL."


@pytest.fixture
def parse_ok(monkeypatch):
    monkeypatch.setattr("app.routers.students.extract_structured", lambda *a: ParsedResume(skills=["Python", "FastAPI"]))


def _add(client, files=None, **overrides):
    return client.post("/students", data={**ACADEMIC, **overrides}, files=files or {})


def _upload(client, login_as, content=CV_V1, email="riya@uni.edu", filename="cv.txt"):
    login_as("student", email=email)
    return client.put("/students/me/resume", files={"resume": (filename, content, "text/plain")})


# ── Office adds students without a CV ────────────────────────────────────────

def test_office_adds_student_without_cv(client: TestClient) -> None:
    response = _add(client)
    assert response.status_code == 200, response.json()
    detail = client.get(f"/students/{response.json()['id']}").json()
    assert detail["has_resume"] is False and detail["resume_updated_at"] is None
    [row] = client.get("/students").json()
    assert row["has_resume"] is False


def test_email_required_when_no_cv(client: TestClient) -> None:
    response = _add(client, email="")
    assert response.status_code == 422
    assert "login email" in response.json()["detail"]


def test_office_can_still_attach_a_cv(client: TestClient, parse_ok) -> None:
    response = _add(client, files={"resume": ("cv.txt", CV_V1, "text/plain")})
    detail = client.get(f"/students/{response.json()['id']}").json()
    assert detail["has_resume"] is True and detail["parsed_resume"]["skills"] == ["Python", "FastAPI"]


# ── Students upload / replace their own CV ───────────────────────────────────

def test_student_uploads_and_replaces_cv_same_record(client: TestClient, login_as, parse_ok) -> None:
    student_id = _add(client).json()["id"]

    first = _upload(client, login_as)
    assert first.status_code == 200, first.json()
    assert first.json()["id"] == student_id
    assert first.json()["has_resume"] is True and first.json()["resume_updated_at"]

    second = _upload(client, login_as, CV_V2)
    assert second.json()["id"] == student_id  # a new CV never creates a new student
    assert second.json()["resume_text"] == CV_V2.decode()
    login_as("officer", email="tpo@uni.edu")
    assert len(client.get("/students").json()) == 1


def test_student_cannot_change_academic_fields(client: TestClient, login_as, parse_ok) -> None:
    student_id = _add(client).json()["id"]
    _upload(client, login_as)
    login_as("officer", email="tpo@uni.edu")
    profile = client.get(f"/students/{student_id}").json()["profile"]
    assert (profile["cgpa"], profile["branch"], profile["batch"]) == (8.6, "CSE", "2027")


def test_unlinked_student_cannot_upload(client: TestClient, login_as) -> None:
    _add(client)
    response = _upload(client, login_as, email="someone.else@uni.edu")
    assert response.status_code == 404
    assert "placement office" in response.json()["detail"]


@pytest.mark.parametrize("role", ["officer", "recruiter", "admin"])
def test_only_students_use_the_self_upload(client: TestClient, login_as, role) -> None:
    login_as(role, email=f"{role}@uni.edu")
    response = client.put("/students/me/resume", files={"resume": ("cv.txt", CV_V1, "text/plain")})
    assert response.status_code == 403


def test_bad_cv_files_are_rejected_and_nothing_changes(client: TestClient, login_as) -> None:
    _add(client)
    assert _upload(client, login_as, b"PK\x03\x04", filename="cv.docx").status_code == 415
    assert _upload(client, login_as, b"", filename="cv.txt").status_code == 400
    assert db.get_student_by_email("riya@uni.edu")["resume_text"] == ""


def test_office_update_keeps_students_cv(client: TestClient, login_as, parse_ok) -> None:
    student_id = _add(client).json()["id"]
    _upload(client, login_as)
    login_as("officer", email="tpo@uni.edu")
    again = _add(client, cgpa="9.1")  # office corrects the CGPA, no CV attached
    assert again.json()["id"] == student_id
    detail = client.get(f"/students/{student_id}").json()
    assert detail["profile"]["cgpa"] == 9.1
    assert detail["resume_text"] == CV_V1.decode()  # the student's CV is untouched


def test_existing_records_are_reused_not_duplicated(client: TestClient, parse_ok) -> None:
    """Records created before stable ids (id hashed from the CV) are found and updated."""
    files = {"resume": ("cv.txt", CV_V1, "text/plain")}
    first = _add(client, email="", files=files).json()["id"]
    second = _add(client, email="", files=files, cgpa="7.9").json()["id"]
    assert first == second and len(client.get("/students").json()) == 1


# ── Ranking and auto-apply without a CV ─────────────────────────────────────

@pytest.fixture
def jd_and_policy(client: TestClient, monkeypatch):
    calls = []

    def counting(text, schema, instructions):
        calls.append(text)
        return _evidence_from_resume(text, schema, instructions)

    monkeypatch.setattr(scoring, "extract_structured", counting)
    monkeypatch.setattr("app.services.matching.retrieve", lambda *a, **k: [])
    jd = JDRequirements(company="Acme", role="SDE", required_skills=["Python", "FastAPI"], preferred_skills=["SQL"])
    return {"policy": _post_policy(client, monkeypatch, PolicyRules(min_cgpa=7.0)), "jd": _post_jd(client, monkeypatch, jd), "calls": calls}


def test_eligible_student_without_cv_is_unscored_without_ai_call(client: TestClient, jd_and_policy) -> None:
    _add(client)
    data = client.get(f"/jds/{jd_and_policy['jd']}/ranked", params={"policy_id": jd_and_policy["policy"]}).json()
    [result] = data["eligible"]
    assert result["score_source"] == "no_resume"
    assert result["score_breakdown"]["score"] is None
    assert result["score_breakdown"]["missing_required"] == ["Python", "FastAPI"]
    assert result["auto_apply_recommended"] is False
    assert jd_and_policy["calls"] == []


def test_auto_apply_skips_students_without_cv(client: TestClient, login_as, jd_and_policy) -> None:
    _add(client)
    login_as("student", email="riya@uni.edu")
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 80})
    login_as("officer", email="tpo@uni.edu")
    run = client.post(f"/jds/{jd_and_policy['jd']}/auto-apply", params={"policy_id": jd_and_policy["policy"]}).json()
    assert run["created"] == []
    assert run["skipped"][0]["reason"] == "Has not uploaded a CV yet."
    assert jd_and_policy["calls"] == []


def test_application_keeps_the_cv_it_was_scored_on(client: TestClient, login_as, jd_and_policy, parse_ok) -> None:
    _add(client)
    _upload(client, login_as)
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 80})
    login_as("officer", email="tpo@uni.edu")
    [created] = client.post(
        f"/jds/{jd_and_policy['jd']}/auto-apply", params={"policy_id": jd_and_policy["policy"]}
    ).json()["created"]

    _upload(client, login_as, CV_V2)  # the student replaces their CV afterwards
    pinned = db.get_application(created["id"])
    assert pinned["resume_sha"] == hashlib.sha256(CV_V1.decode().encode()).hexdigest()
    assert pinned["student_id"] == created["student_id"]  # same student record
