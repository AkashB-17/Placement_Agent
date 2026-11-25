"""PUT /jds/{id}/deadline: recruiters (own jobs) and staff extend or shorten a deadline."""
from __future__ import annotations

from datetime import UTC, datetime

from app.schemas import JDRequirements
from tests.test_apply_and_tips import _login_student
from tests.test_match import _post_jd
from tests.test_my_jobs import board, clock  # noqa: F401  (fixtures)

ACME_JD = JDRequirements(company="Acme", role="SDE", ctc="10 LPA", required_skills=["Python", "FastAPI"], deadline="2026-12-05")


def _set(client, jd_id, deadline):
    return client.put(f"/jds/{jd_id}/deadline", json={"deadline": deadline})


def _job(client, company):
    return next(j for j in client.get("/me/jobs").json()["jobs"] if j["company"] == company)


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_extending_reopens_a_closed_job(client, board, login_as) -> None:
    login_as("officer", email="tpo@uni.edu")
    response = _set(client, board["closed"], "2026-12-10")
    assert response.status_code == 200, response.json()
    change = response.json()
    assert change["previous_deadline"] == "November 15, 2026" and change["rescheduled"] == 0
    assert _when(change["deadline_at"]) == datetime(2026, 12, 10, 18, 29, 59, 999999, tzinfo=UTC)

    detail = client.get(f"/jds/{board['closed']}").json()
    assert detail["requirements"]["deadline"] == "2026-12-10"
    assert detail["original_deadline"] == "November 15, 2026" and detail["deadline_changed_at"]

    _login_student(login_as)
    oldco = _job(client, "Oldco")
    assert oldco["closed"] is False and oldco["deadline"] == "2026-12-10" and oldco["deadline_changed_at"]


def test_extending_leaves_pending_applications_alone(client, board, login_as) -> None:
    _login_student(login_as)
    app = client.post(f"/me/jobs/{board['open']}/apply").json()
    login_as("officer", email="tpo@uni.edu")
    assert _set(client, board["open"], "2026-12-30").json()["rescheduled"] == 0
    _login_student(login_as)
    [listed] = client.get("/me/applications").json()
    assert listed["release_at"] == app["release_at"] and listed["status"] == "pending"


def test_shortening_moves_pending_applications_earlier_and_notifies(client, board, login_as) -> None:
    _login_student(login_as)
    app = client.post(f"/me/jobs/{board['open']}/apply").json()  # release 21 Nov 06:00 UTC
    login_as("officer", email="tpo@uni.edu")
    change = _set(client, board["open"], "2026-11-20").json()  # closes 20 Nov 18:29:59.999999 UTC
    assert change["rescheduled"] == 1

    _login_student(login_as)
    [listed] = client.get("/me/applications").json()
    # 6 h before the new deadline, still pending and withdrawable.
    assert _when(listed["release_at"]) == datetime(2026, 11, 20, 12, 29, 59, 999999, tzinfo=UTC)
    assert listed["status"] == "pending" and listed["can_withdraw"] is True
    assert _when(listed["release_at"]) < _when(app["release_at"])
    notes = [n["message"] for n in client.get("/me/notifications").json()]
    assert any("moved its deadline" in m and "Withdraw before then" in m for m in notes)


def test_shortening_to_almost_now_sends_at_once(client, board, login_as, clock) -> None:
    _login_student(login_as)
    client.post(f"/me/jobs/{board['open']}/apply")
    clock(minutes=1)
    login_as("officer", email="tpo@uni.edu")
    # 11:35 IST = 06:05 UTC: 4 min away, past both the buffer and the last call.
    assert _set(client, board["open"], "2026-11-20T11:35").json()["rescheduled"] == 1
    _login_student(login_as)
    [listed] = client.get("/me/applications").json()
    assert listed["status"] == "submitted"
    notes = [n["message"] for n in client.get("/me/notifications").json()]
    assert any("will be sent now" in m for m in notes)


def test_sent_and_withdrawn_applications_are_untouched(client, board, login_as, clock) -> None:
    _login_student(login_as)
    app = client.post(f"/me/jobs/{board['open']}/apply").json()
    client.post(f"/applications/{app['id']}/withdraw")
    login_as("officer", email="tpo@uni.edu")
    assert _set(client, board["open"], "2026-11-20").json()["rescheduled"] == 0
    _login_student(login_as)
    assert client.get("/me/applications").json()[0]["status"] == "withdrawn"


def test_reuploading_the_jd_keeps_the_new_deadline(client, board, login_as, monkeypatch) -> None:
    login_as("officer", email="tpo@uni.edu")
    _set(client, board["open"], "2026-12-20")
    login_as("admin")
    assert _post_jd(client, monkeypatch, ACME_JD) == board["open"]  # same text, same job
    assert client.get(f"/jds/{board['open']}").json()["requirements"]["deadline"] == "2026-12-20"


def test_recruiter_edits_only_their_own_jobs(client, board, login_as, monkeypatch) -> None:
    owner = login_as("recruiter", email="hr@volt.com")
    own = _post_jd(client, monkeypatch, JDRequirements(company="Volt", role="QA", required_skills=["Python"], deadline="2026-12-01"))
    listed = {j["id"]: j for j in client.get("/jds").json()}
    assert listed[own]["can_edit_deadline"] is True and listed[board["open"]]["can_edit_deadline"] is False
    assert _set(client, own, "2026-12-15").status_code == 200

    assert _set(client, board["open"], "2026-12-15").status_code == 404  # not theirs: looks missing
    login_as("recruiter", email="hr@other.com")
    assert _set(client, own, "2026-12-15").status_code == 404
    assert owner.role == "recruiter"


def test_students_cannot_change_deadlines(client, board, login_as) -> None:
    _login_student(login_as)
    assert _set(client, board["open"], "2026-12-15").status_code == 403
    assert all(j["can_edit_deadline"] is False for j in client.get("/jds").json())


def test_bad_input(client, board, login_as) -> None:
    login_as("officer", email="tpo@uni.edu")
    bad = _set(client, board["open"], "next friday!!")
    assert bad.status_code == 422 and "2026-12-05" in bad.json()["detail"]
    assert _set(client, "nope", "2026-12-15").status_code == 404
