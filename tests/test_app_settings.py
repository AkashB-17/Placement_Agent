"""Admin-set auto-apply threshold (GET/PUT /admin/settings) and everything that reads it."""
from __future__ import annotations

import pytest

from app.schemas import JDRequirements
from tests.test_apply_and_tips import _login_student
from tests.test_match import _post_jd
from tests.test_my_jobs import board, clock  # noqa: F401  (fixtures)


@pytest.fixture
def three_of_four(client, board, login_as, monkeypatch) -> str:
    """A JD where the student's CV shows 3 of 4 required skills: score 75."""
    login_as("admin")
    return _post_jd(client, monkeypatch, JDRequirements(
        company="Gridline", role="Backend", required_skills=["Python", "FastAPI", "SQL", "Docker"], deadline="2026-12-20"))


def _set(client, value):
    return client.put("/admin/settings", json={"auto_apply_threshold": value})


def _match(client, board, jd_id):
    student_id = client.get("/students").json()[0]["id"]
    return client.post("/match", json={"jd_id": jd_id, "student_id": student_id, "policy_id": board["policy"]}).json()


def test_default_comes_from_config(client, board, login_as) -> None:
    login_as("admin")
    assert client.get("/admin/settings").json() == {
        "auto_apply_threshold": 80.0, "default_auto_apply_threshold": 80.0, "updated_at": None,
    }


def test_new_threshold_applies_to_rankings_and_the_flag(client, board, three_of_four) -> None:
    result = _match(client, board, three_of_four)
    assert result["score_breakdown"]["score"] == 75.0 and result["auto_apply_recommended"] is False

    saved = _set(client, 70).json()
    assert saved["auto_apply_threshold"] == 70.0 and saved["updated_at"]
    assert client.get("/admin/settings").json()["auto_apply_threshold"] == 70.0
    assert _match(client, board, three_of_four)["auto_apply_recommended"] is True
    ranked = client.get(f"/jds/{three_of_four}/ranked", params={"policy_id": board["policy"]}).json()
    assert ranked["auto_apply_threshold"] == 70.0


def test_students_can_set_a_bar_down_to_the_new_threshold(client, board, login_as) -> None:
    login_as("admin")
    _set(client, 70)
    _login_student(login_as)
    prefs = client.get("/me/auto-apply").json()
    assert prefs["threshold"] == 70.0 and prefs["min_score"] == 70.0
    assert client.put("/me/auto-apply", json={"enabled": True, "min_score": 72}).status_code == 200
    assert client.put("/me/auto-apply", json={"enabled": True, "min_score": 65}).status_code == 422


def test_auto_apply_runs_use_the_threshold(client, board, three_of_four, login_as) -> None:
    _set(client, 70)
    _login_student(login_as)
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 70})
    login_as("officer", email="tpo@uni.edu")
    run = client.post(f"/jds/{three_of_four}/auto-apply", params={"policy_id": board["policy"]}).json()
    assert len(run["created"]) == 1 and run["created"][0]["score"] == 75.0


def test_raising_it_above_a_students_bar_wins(client, board, three_of_four, login_as) -> None:
    _set(client, 70)
    _login_student(login_as)
    client.put("/me/auto-apply", json={"enabled": True, "min_score": 72})
    login_as("admin")
    _set(client, 90)
    login_as("officer", email="tpo@uni.edu")
    run = client.post(f"/jds/{three_of_four}/auto-apply", params={"policy_id": board["policy"]}).json()
    assert run["created"] == []
    assert "below their bar of 90" in run["skipped"][0]["reason"]


@pytest.mark.parametrize("value", [-1, 100.5, "high"])
def test_invalid_values(client, board, login_as, value) -> None:
    login_as("admin")
    assert _set(client, value).status_code == 422


@pytest.mark.parametrize("role", ["officer", "recruiter", "student"])
def test_only_admins(client, board, login_as, role) -> None:
    login_as(role, email=f"{role}@uni.edu")
    assert client.get("/admin/settings").status_code == 403
    assert _set(client, 50).status_code == 403
