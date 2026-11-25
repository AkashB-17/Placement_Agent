"""Admin job management: PUT /jds/{id} (edit details) and DELETE /jds/{id} (remove)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app import db
from tests.test_apply_and_tips import _login_student
from tests.test_jd_deadline import ACME_JD
from tests.test_match import _post_jd
from tests.test_my_jobs import board, clock  # noqa: F401  (fixtures)

EDIT = {
    "company": "Acme", "role": "SDE", "required_skills": ["Python", "FastAPI"], "preferred_skills": [],
    "min_cgpa_override": None, "allowed_branches": [], "allowed_batches": [], "ctc": "10 LPA",
    "deadline": "2026-12-05", "experience_required": None,
}


@pytest.fixture(autouse=True)
def _as_admin(board, login_as) -> None:
    login_as("admin")  # the board fixture ends signed in as the student


def _edit(client, jd_id, **changes):
    return client.put(f"/jds/{jd_id}", json={**EDIT, **changes})


def _student_id(client) -> str:
    return client.get("/students").json()[0]["id"]


def test_admin_edits_details_and_eligibility_follows(client, board, login_as) -> None:
    response = _edit(
        client, board["open"], role="  Software Engineer ", min_cgpa_override=9.0,
        allowed_branches=["Computer Science"], allowed_batches=["2026-27"], ctc="12 LPA",
        required_skills=["Python", "python", " FastAPI "], preferred_skills=["Docker", "Python"],
    )
    assert response.status_code == 200, response.json()
    detail = response.json()
    req = detail["requirements"]
    assert req["role"] == "Software Engineer" and req["ctc"] == "12 LPA"
    assert req["required_skills"] == ["Python", "FastAPI"]  # trimmed, de-duplicated
    assert req["preferred_skills"] == ["Docker"]  # a required skill isn't also preferred
    assert req["allowed_branches"] == ["CSE"] and req["allowed_batches"] == ["2027"]
    assert detail["edited_at"]

    _login_student(login_as)  # Riya: CGPA 8.6 now misses the 9.0 the admin set
    acme = next(j for j in client.get("/me/jobs").json()["jobs"] if j["company"] == "Acme")
    [rule] = acme["eligibility"]["failed_rules"]
    assert rule["rule"] == "min_cgpa" and rule["source"] == "jd" and rule["required_value"] == 9.0


def test_changed_skills_are_rescored(client, board) -> None:
    body = {"jd_id": board["open"], "student_id": _student_id(client), "policy_id": board["policy"]}
    assert client.post("/match", json=body).json()["score_breakdown"]["score"] == 100.0
    _edit(client, board["open"], required_skills=["Python", "Kubernetes"])
    after = client.post("/match", json=body).json()["score_breakdown"]
    assert after["score"] == 50.0 and after["missing_required"] == ["Kubernetes"]


def test_extracted_details_are_kept_and_survive_reupload(client, board, monkeypatch) -> None:
    _edit(client, board["open"], role="Platform Engineer")
    assert db.get_jd_extracted_requirements(board["open"])["role"] == "SDE"
    assert _post_jd(client, monkeypatch, ACME_JD) == board["open"]  # same text re-uploaded
    assert client.get(f"/jds/{board['open']}").json()["requirements"]["role"] == "Platform Engineer"


def test_deadline_edit_reschedules_pending_applications(client, board, login_as) -> None:
    _login_student(login_as)
    client.post(f"/me/jobs/{board['open']}/apply")
    login_as("admin")
    assert _edit(client, board["open"], deadline="2026-11-20").status_code == 200
    _login_student(login_as)
    [app] = client.get("/me/applications").json()
    assert datetime.fromisoformat(app["release_at"]) == datetime(2026, 11, 20, 12, 29, 59, 999999, tzinfo=UTC)
    assert client.get(f"/jds/{board['open']}").json()["requirements"]["deadline"] == "2026-11-20"


def test_bad_deadline_saves_nothing(client, board) -> None:
    response = _edit(client, board["open"], deadline="soon-ish", role="Changed")
    assert response.status_code == 422
    assert client.get(f"/jds/{board['open']}").json()["requirements"]["role"] == "SDE"
    assert _edit(client, board["open"], deadline=None).status_code == 422  # can't remove one


@pytest.mark.parametrize("changes", [{"required_skills": []}, {"required_skills": ["  "]}, {"min_cgpa_override": 11}])
def test_invalid_edits(client, board, changes) -> None:
    assert _edit(client, board["open"], **changes).status_code == 422


def test_admin_removes_a_job_with_its_applications(client, board, login_as) -> None:
    _login_student(login_as)
    client.post(f"/me/jobs/{board['open']}/apply")
    login_as("admin")
    client.post("/match", json={"jd_id": board["open"], "student_id": _student_id(client), "policy_id": board["policy"]})
    assert db._fetchone("SELECT COUNT(*) AS n FROM score_cache WHERE jd_id = ?", (board["open"],))["n"] == 1

    response = client.delete(f"/jds/{board['open']}")
    assert response.status_code == 200, response.json()
    assert response.json() == {"id": board["open"], "applications_removed": 1, "students_notified": 1}
    assert client.get(f"/jds/{board['open']}").status_code == 404
    assert db._fetchone("SELECT COUNT(*) AS n FROM score_cache WHERE jd_id = ?", (board["open"],))["n"] == 0

    _login_student(login_as)
    assert client.get("/me/applications").json() == []
    assert "Acme" not in {j["company"] for j in client.get("/me/jobs").json()["jobs"]}
    [note] = client.get("/me/notifications").json()  # the application's own notice went with it
    assert note["message"].startswith("Acme – SDE was removed") and note["application_id"] is None


def test_removing_a_job_without_applications(client, board) -> None:
    assert client.delete(f"/jds/{board['ece']}").json() == {"id": board["ece"], "applications_removed": 0, "students_notified": 0}
    assert client.delete(f"/jds/{board['ece']}").status_code == 404


@pytest.mark.parametrize("role", ["officer", "recruiter", "student"])
def test_only_admins_edit_or_remove(client, board, login_as, role) -> None:
    login_as(role, email=f"{role}@uni.edu")
    assert _edit(client, board["open"]).status_code == 403
    assert client.delete(f"/jds/{board['open']}").status_code == 403


def test_unknown_job_404(client, board) -> None:
    assert _edit(client, "nope").status_code == 404
    assert client.delete("/jds/nope").status_code == 404
