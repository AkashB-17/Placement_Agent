"""Self sign-up: students ask to be added (POST /me/registration); staff approve or reject."""
from __future__ import annotations

import pytest

from tests.test_student_cv import _add

STUDENT_ID = "11111111-1111-1111-1111-111111111111"
EMAIL = "neha@uni.edu"
DETAILS = {"name": "Neha  Kapoor", "branch": "Computer Science", "batch": "2023-27", "cgpa": 8.4, "active_backlogs": 0}


@pytest.fixture
def as_student(login_as):
    return lambda: login_as("student", email=EMAIL, user_id=STUDENT_ID)


def _submit(client, as_student, **changes):
    as_student()
    return client.post("/me/registration", json={**DETAILS, **changes})


def test_unlinked_student_has_nothing_yet(client, as_student) -> None:
    as_student()
    assert client.get("/me/registration").json() == {"linked": False, "request": None}
    assert client.get("/students/me").status_code == 404


def test_request_is_queued_for_staff(client, as_student, login_as) -> None:
    response = _submit(client, as_student)
    assert response.status_code == 200, response.json()
    request = response.json()["request"]
    assert request["status"] == "pending" and request["email"] == EMAIL
    assert request["name"] == "Neha Kapoor" and request["branch"] == "CSE" and request["batch"] == "2027"

    login_as("officer", email="tpo@uni.edu")
    [queued] = client.get("/registrations").json()
    assert queued["user_id"] == STUDENT_ID and queued["status"] == "pending"


def test_approval_creates_the_record_and_links_the_account(client, as_student, login_as) -> None:
    _submit(client, as_student)
    login_as("officer", email="tpo@uni.edu")
    approved = client.post(f"/registrations/{STUDENT_ID}/approve")
    assert approved.status_code == 200, approved.json()
    assert approved.json()["status"] == "approved" and approved.json()["decided_at"]
    assert client.get("/registrations").json() == []  # nothing pending any more

    as_student()
    assert client.get("/me/registration").json()["linked"] is True
    me = client.get("/students/me").json()
    assert me["profile"]["name"] == "Neha Kapoor" and me["profile"]["cgpa"] == 8.4 and me["has_resume"] is False
    # The record is the office's from now on: resubmitting isn't possible.
    assert client.post("/me/registration", json=DETAILS).status_code == 409


def test_staff_can_correct_values_when_approving(client, as_student, login_as) -> None:
    _submit(client, as_student)
    login_as("admin")
    corrected = {**DETAILS, "cgpa": 7.9, "active_backlogs": 1}
    assert client.post(f"/registrations/{STUDENT_ID}/approve", json=corrected).status_code == 200
    student = next(s for s in client.get("/students").json() if s["email"] == EMAIL)
    assert student["cgpa"] == 7.9 and student["active_backlogs"] == 1


def test_rejection_shows_the_reason_and_allows_resubmitting(client, as_student, login_as) -> None:
    _submit(client, as_student)
    login_as("officer", email="tpo@uni.edu")
    rejected = client.post(f"/registrations/{STUDENT_ID}/reject", json={"note": "CGPA doesn't match our records."})
    assert rejected.json()["status"] == "rejected"

    as_student()
    mine = client.get("/me/registration").json()["request"]
    assert mine["status"] == "rejected" and mine["note"] == "CGPA doesn't match our records."
    again = _submit(client, as_student, cgpa=7.2).json()["request"]
    assert again["status"] == "pending" and again["note"] is None and again["cgpa"] == 7.2


def test_if_the_office_already_added_them_the_record_is_kept(client, as_student, login_as) -> None:
    _submit(client, as_student)
    login_as("admin")
    _add(client, name="Neha Kapoor", email=EMAIL, cgpa="9.1")  # office adds them meanwhile
    assert client.post(f"/registrations/{STUDENT_ID}/approve").status_code == 200
    [student] = [s for s in client.get("/students").json() if s["email"] == EMAIL]
    assert student["cgpa"] == 9.1  # the office's record wins, no duplicate


def test_linked_students_cannot_request(client, login_as) -> None:
    _add(client, name="Riya Sen", email="riya@uni.edu")
    login_as("student", email="riya@uni.edu")
    assert client.post("/me/registration", json=DETAILS).status_code == 409


def test_a_request_is_decided_once(client, as_student, login_as) -> None:
    _submit(client, as_student)
    login_as("officer", email="tpo@uni.edu")
    client.post(f"/registrations/{STUDENT_ID}/approve")
    assert client.post(f"/registrations/{STUDENT_ID}/approve").status_code == 409
    assert client.post(f"/registrations/{STUDENT_ID}/reject", json={"note": "no"}).status_code == 409
    assert client.post("/registrations/00000000-0000-0000-0000-000000000000/approve").status_code == 404


@pytest.mark.parametrize("changes", [{"cgpa": 11}, {"active_backlogs": -1}, {"name": ""}, {"branch": "   "}])
def test_invalid_requests(client, as_student, changes) -> None:
    assert _submit(client, as_student, **changes).status_code == 422


def test_roles(client, as_student, login_as) -> None:
    _submit(client, as_student)
    assert client.get("/registrations").status_code == 403  # still the student
    assert client.post(f"/registrations/{STUDENT_ID}/approve").status_code == 403
    login_as("recruiter", email="hr@acme.com")
    assert client.get("/registrations").status_code == 403
    login_as("officer", email="tpo@uni.edu")
    assert client.post("/me/registration", json=DETAILS).status_code == 403
    assert client.get("/registrations", params={"status": "approved"}).json() == []
