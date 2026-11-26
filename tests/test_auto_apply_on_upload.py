"""Auto-apply runs by itself, in the background, whenever a JD is uploaded."""
from __future__ import annotations

import pytest

from app.config import set_settings
from app.schemas import JDRequirements, PolicyRules
from tests.conftest import make_test_settings
from tests.test_apply_and_tips import _login_student
from tests.test_match import _post_jd, _post_policy
from tests.test_my_jobs import board, clock  # noqa: F401  (fixtures)

STRONG = JDRequirements(company="Nimbus", role="API Engineer", required_skills=["Python", "FastAPI"], deadline="2026-12-20")


@pytest.fixture
def on_upload(tmp_path, board, login_as):
    """Turn the automatic run on, and opt the student (Riya, CV: Python, FastAPI, SQL) in at 80."""
    set_settings(make_test_settings(tmp_path, auto_apply_on_upload=True))
    _login_student(login_as)
    return {"enabled": True, "min_score": 80}


def test_uploading_a_jd_auto_applies_for_qualifying_students(client, on_upload, login_as, monkeypatch) -> None:
    client.put("/me/auto-apply", json=on_upload)
    login_as("officer", email="tpo@uni.edu")
    monkeypatch.setattr("app.routers.jds.extract_structured", lambda *a: STRONG)
    response = client.post("/jds", data={"text": "Nimbus API Engineer JD"})
    assert response.status_code == 200
    assert "running in the background" in response.json()["auto_apply"]

    _login_student(login_as)  # the background run has finished when the response returns
    [app] = client.get("/me/applications").json()
    assert app["company"] == "Nimbus" and app["status"] == "pending" and app["source"] == "auto"
    assert app["score"] == 100.0 and app["can_withdraw"] is True
    notes = [n["message"] for n in client.get("/me/notifications").json()]
    assert any(m.startswith("We applied to Nimbus – API Engineer for you") for m in notes)


def test_students_below_their_bar_or_not_opted_in_are_left_alone(client, on_upload, login_as, monkeypatch) -> None:
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 90})
    login_as("officer", email="tpo@uni.edu")
    _post_jd(client, monkeypatch, JDRequirements(company="Halfway", role="SRE", required_skills=["Python", "Kubernetes"], deadline="2026-12-20"))
    _login_student(login_as)
    assert client.get("/me/applications").json() == []  # score 50 < 90

    client.put("/me/auto-apply", json={"enabled": False, "min_score": 80})
    login_as("officer", email="tpo@uni.edu")
    _post_jd(client, monkeypatch, STRONG)
    _login_student(login_as)
    assert client.get("/me/applications").json() == []  # opted out


def test_reuploading_the_same_jd_never_applies_twice(client, on_upload, login_as, monkeypatch) -> None:
    client.put("/me/auto-apply", json=on_upload)
    login_as("officer", email="tpo@uni.edu")
    first = _post_jd(client, monkeypatch, STRONG)
    assert _post_jd(client, monkeypatch, STRONG) == first
    _login_student(login_as)
    assert len(client.get("/me/applications").json()) == 1


def test_past_deadline_or_no_policy_upload_still_succeeds(client, tmp_path, login_as, monkeypatch) -> None:
    set_settings(make_test_settings(tmp_path, auto_apply_on_upload=True))
    login_as("officer", email="tpo@uni.edu")
    # No policy yet: the upload works, auto-apply is skipped quietly.
    monkeypatch.setattr("app.routers.jds.extract_structured", lambda *a: STRONG)
    assert client.post("/jds", data={"text": "first"}).status_code == 200
    _post_policy(client, monkeypatch, PolicyRules(min_cgpa=7.0))
    # Deadline already passed: same.
    old = JDRequirements(company="Late", role="Dev", required_skills=["Python"], deadline="2026-11-01")
    monkeypatch.setattr("app.routers.jds.extract_structured", lambda *a: old)
    assert client.post("/jds", data={"text": "late"}).status_code == 200


def test_switched_off(client, board, login_as, monkeypatch) -> None:
    _login_student(login_as)
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 80})
    login_as("officer", email="tpo@uni.edu")
    monkeypatch.setattr("app.routers.jds.extract_structured", lambda *a: STRONG)
    response = client.post("/jds", data={"text": "Nimbus"})
    assert response.json()["auto_apply"] is None
    _login_student(login_as)
    assert client.get("/me/applications").json() == []


# ── Run history (GET /auto-apply/runs) ──────────────────────────────────────

def _runs(client, login_as, jd_id=None):
    login_as("officer", email="tpo@uni.edu")
    return client.get("/auto-apply/runs", params={"jd_id": jd_id} if jd_id else {}).json()


def test_automatic_run_is_recorded_with_its_outcome(client, on_upload, login_as, monkeypatch) -> None:
    client.put("/me/auto-apply", json=on_upload)
    login_as("officer", email="tpo@uni.edu")
    jd_id = _post_jd(client, monkeypatch, STRONG)
    [run] = _runs(client, login_as, jd_id)
    assert run["trigger"] == "upload" and run["status"] == "completed"
    assert run["applied"] == 1 and run["skipped"] == [] and run["message"] is None


def test_near_misses_are_visible_with_the_reason(client, on_upload, login_as, monkeypatch) -> None:
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 90})
    login_as("officer", email="tpo@uni.edu")
    jd_id = _post_jd(client, monkeypatch, JDRequirements(company="Halfway", role="SRE", required_skills=["Python", "Kubernetes"], deadline="2026-12-20"))
    [run] = _runs(client, login_as, jd_id)
    assert run["applied"] == 0
    [skip] = run["skipped"]
    assert skip["student_name"] == "Riya Sen" and skip["reason"] == "Score 50.0 is below their bar of 90."


def test_skipped_runs_say_why(client, tmp_path, login_as, monkeypatch) -> None:
    set_settings(make_test_settings(tmp_path, auto_apply_on_upload=True))
    login_as("officer", email="tpo@uni.edu")
    monkeypatch.setattr("app.routers.jds.extract_structured", lambda *a: STRONG)
    client.post("/jds", data={"text": "first"})
    [run] = client.get("/auto-apply/runs").json()
    assert run["status"] == "skipped" and run["message"] == "No placement policy has been uploaded yet."

    _post_policy(client, monkeypatch, PolicyRules(min_cgpa=7.0))
    late = _post_jd(client, monkeypatch, JDRequirements(company="Late", role="Dev", required_skills=["Python"], deadline="2026-11-01"))
    [run] = client.get("/auto-apply/runs", params={"jd_id": late}).json()
    assert run["status"] == "skipped" and "has passed" in run["message"]


def test_staff_runs_are_recorded_too_newest_first(client, board, login_as) -> None:
    login_as("officer", email="tpo@uni.edu")
    for _ in range(2):
        client.post(f"/jds/{board['open']}/auto-apply", params={"policy_id": board["policy"]})
    runs = client.get("/auto-apply/runs", params={"jd_id": board["open"]}).json()
    assert [r["trigger"] for r in runs] == ["manual", "manual"]
    assert runs[0]["ran_at"] >= runs[1]["ran_at"]


def test_removing_a_job_removes_its_runs(client, board, login_as) -> None:
    login_as("officer", email="tpo@uni.edu")
    client.post(f"/jds/{board['open']}/auto-apply", params={"policy_id": board["policy"]})
    login_as("admin")
    client.delete(f"/jds/{board['open']}")
    assert client.get("/auto-apply/runs", params={"jd_id": board["open"]}).json() == []


@pytest.mark.parametrize("role", ["recruiter", "student"])
def test_run_history_is_staff_only(client, board, login_as, role) -> None:
    login_as(role, email=f"{role}@uni.edu")
    assert client.get("/auto-apply/runs").status_code == 403
