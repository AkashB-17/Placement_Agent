"""PUT /students/{id}: the placement office edits a student's academic record."""
from __future__ import annotations

import pytest

from app.schemas import JDRequirements, PolicyRules
from tests.test_match import _post_jd, _post_policy
from tests.test_student_cv import _add, _upload, parse_ok  # noqa: F401  (fixture)

EDIT = {"name": "Riya Sen", "email": "riya@uni.edu", "branch": "CSE", "batch": "2027",
        "cgpa": 8.6, "active_backlogs": 0, "is_placed": False}


def _edit(client, student_id, **changes):
    return client.put(f"/students/{student_id}", json={**EDIT, **changes})


def test_office_edits_academic_record(client) -> None:
    sid = _add(client).json()["id"]
    response = _edit(client, sid, name="Riya S. Sen", cgpa=9.1, active_backlogs=1, branch="Computer Science", batch="2027-28", is_placed=True)
    assert response.status_code == 200, response.json()
    profile = response.json()["profile"]
    assert profile == {  # branch and batch normalised as on create ("2027-28" graduates in 2028)
        "name": "Riya S. Sen", "email": "riya@uni.edu", "branch": "CSE", "batch": "2028",
        "cgpa": 9.1, "active_backlogs": 1, "is_placed": True, "parsed_resume": None,
    }
    assert response.json()["id"] == sid
    listed = next(s for s in client.get("/students").json() if s["id"] == sid)
    assert listed["cgpa"] == 9.1 and listed["is_placed"] is True


def test_edit_keeps_the_students_cv(client, login_as, parse_ok) -> None:
    sid = _add(client).json()["id"]
    _upload(client, login_as)
    login_as("officer", email="tpo@uni.edu")
    detail = _edit(client, sid, cgpa=7.2).json()
    assert detail["has_resume"] is True and detail["parsed_resume"]["skills"] == ["Python", "FastAPI"]
    assert detail["profile"]["cgpa"] == 7.2


def test_new_cgpa_applies_to_eligibility_at_once(client, login_as, monkeypatch) -> None:
    _post_policy(client, monkeypatch, PolicyRules(min_cgpa=8.0))
    _post_jd(client, monkeypatch, JDRequirements(company="Acme", role="SDE", required_skills=["Python"]))
    sid = _add(client).json()["id"]
    _edit(client, sid, cgpa=7.5)
    login_as("student", email="riya@uni.edu")
    [job] = client.get("/me/jobs").json()["jobs"]
    assert job["eligibility"]["eligible"] is False
    assert job["eligibility"]["failed_rules"][0]["rule"] == "min_cgpa"


def test_email_change_moves_the_login_link(client, login_as) -> None:
    sid = _add(client).json()["id"]
    _edit(client, sid, email="Riya.New@Uni.edu")
    login_as("student", email="riya.new@uni.edu")
    assert client.get("/students/me").json()["id"] == sid
    login_as("student", email="riya@uni.edu")
    assert client.get("/students/me").status_code == 404


def test_email_cannot_belong_to_two_students(client) -> None:
    sid = _add(client).json()["id"]
    _add(client, name="Dev Rao", email="dev@uni.edu")
    response = _edit(client, sid, email="dev@uni.edu")
    assert response.status_code == 409 and "Dev Rao" in response.json()["detail"]


def test_email_required_while_there_is_no_cv(client) -> None:
    sid = _add(client).json()["id"]
    assert _edit(client, sid, email=None).status_code == 422


@pytest.mark.parametrize("changes", [{"cgpa": 10.5}, {"cgpa": -1}, {"active_backlogs": -1}, {"name": ""}, {"email": "not-an-email"}, {"branch": "   "}])
def test_invalid_values_are_rejected(client, changes) -> None:
    sid = _add(client).json()["id"]
    assert _edit(client, sid, **changes).status_code == 422


def test_unknown_student_404(client) -> None:
    assert _edit(client, "nope").status_code == 404


@pytest.mark.parametrize("role", ["student", "recruiter"])
def test_only_staff_can_edit(client, login_as, role) -> None:
    sid = _add(client).json()["id"]
    login_as(role, email="riya@uni.edu")
    assert _edit(client, sid, cgpa=10).status_code == 403
