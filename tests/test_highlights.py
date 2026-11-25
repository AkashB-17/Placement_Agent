"""Code-built "why this candidate stands out" lines on applications."""
from __future__ import annotations

from app.schemas import JDRequirements, PolicyRules, ScoreBreakdown
from app.services.highlights import build_highlights, skill_highlights
from tests.test_apply_and_tips import _login_student
from tests.test_my_jobs import board, clock  # noqa: F401  (fixtures)

STUDENT = {"cgpa": 8.6, "active_backlogs": 0}


def test_full_coverage_cgpa_margin_and_no_backlogs() -> None:
    breakdown = ScoreBreakdown(score=100, matched_required=["Python", "SQL"], matched_preferred=["Docker"])
    lines = build_highlights(STUDENT, PolicyRules(min_cgpa=7.0), JDRequirements(min_cgpa_override=7.5), breakdown)
    assert lines == [
        "Shows all 2 required skills in their CV: Python, SQL",
        "Also shows preferred skills: Docker",
        "CGPA 8.6, 1.1 above the required 7.5",  # the stricter floor, as in eligibility
        "No active backlogs",
    ]


def test_partial_coverage_and_no_cgpa_rule() -> None:
    breakdown = ScoreBreakdown(
        score=60, matched_required=["A", "B", "C", "D", "E"], missing_required=["F"]
    )
    lines = build_highlights({"cgpa": 7.0, "active_backlogs": 2}, PolicyRules(), JDRequirements(), breakdown)
    assert lines == ["Shows 5 of 6 required skills in their CV: A, B, C, D and 1 more", "CGPA 7"]


def test_nothing_matched_says_nothing_about_skills() -> None:
    assert skill_highlights(ScoreBreakdown(score=0, missing_required=["Go"])) == []


def test_application_carries_highlights_snapshot(client, board, login_as) -> None:
    _login_student(login_as)
    app = client.post(f"/me/jobs/{board['open']}/apply").json()
    assert app["highlights"] == [
        "Shows all 2 required skills in their CV: Python, FastAPI",
        "CGPA 8.6, 1.6 above the required 7",
        "No active backlogs",
    ]
    # The breakdown itself is unchanged by the extra snapshot field.
    assert app["score_breakdown"]["matched_required"] == ["Python", "FastAPI"]
    [listed] = client.get("/me/applications").json()
    assert listed["highlights"] == app["highlights"]


def test_older_applications_fall_back_to_skill_lines() -> None:
    from datetime import UTC, datetime

    from app.services.auto_apply import to_out

    now = datetime(2026, 11, 20, tzinfo=UTC)
    row = {
        "id": "a", "student_id": "s", "student_name": "S", "jd_id": "j", "company": "C", "role": "R",
        "policy_id": "p", "status": "submitted", "score": 100.0, "created_at": now, "release_at": now,
        "decided_at": now, "resume_path": None, "source": "auto",
        "match": {"score": 100.0, "matched_required": ["Python"], "missing_required": []},
    }
    assert to_out(row, now).highlights == ["Shows the required skill in their CV: Python"]
