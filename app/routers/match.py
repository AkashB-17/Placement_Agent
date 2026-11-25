"""
POST /match and GET /jds/{jd_id}/ranked. The evaluation itself lives in
app/services/matching.py, shared with auto-apply.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import CurrentUser, require_role, staff_only
from app.db import get_all_students
from app.routers.students import owns_student_record
from app.schemas import MatchRequest, MatchResult, RankedResponse
from app.services.app_settings import auto_apply_threshold
from app.services.matching import evaluate_many, evaluate_student, load_jd, load_policy, load_student

router = APIRouter(tags=["match"])


@router.post("/match", response_model=MatchResult)
def match(
    body: MatchRequest,
    user: CurrentUser = Depends(require_role("officer", "admin", "student")),
) -> MatchResult:
    student = load_student(body.student_id)
    if user.role == "student" and not owns_student_record(user, student):
        # A student may check their own fit only; same 404 as an unknown id.
        raise HTTPException(status_code=404, detail=f"Student '{body.student_id}' not found.")
    policy = load_policy(body.policy_id)
    jd = load_jd(body.jd_id)
    return evaluate_student(student, policy, jd, body.policy_id, body.jd_id)


@router.get("/jds/{jd_id}/ranked", response_model=RankedResponse)
def ranked(
    jd_id: str,
    policy_id: str = Query(..., description="Policy ID to evaluate against"),
    refresh: bool = Query(False, description="Ignore cached scores and re-score every eligible student"),
    _: CurrentUser = Depends(staff_only),
) -> RankedResponse:
    policy = load_policy(policy_id)
    jd = load_jd(jd_id)

    results = evaluate_many(get_all_students(), policy, jd, policy_id, jd_id, refresh=refresh)
    eligible = [r for r in results if r.eligibility.eligible]
    ineligible = [r for r in results if not r.eligibility.eligible]

    # Score descending; unscored (JD without required skills) last; name breaks ties.
    eligible.sort(
        key=lambda r: (
            r.score_breakdown.score is None,
            -(r.score_breakdown.score or 0.0),
            r.student_name,
        )
    )
    ineligible.sort(key=lambda r: r.student_name)
    return RankedResponse(
        jd_id=jd_id,
        policy_id=policy_id,
        auto_apply_threshold=auto_apply_threshold(),
        eligible=eligible,
        ineligible=ineligible,
        ai_calls=sum(r.score_source == "fresh" for r in results),
        cached_scores=sum(r.score_source == "cache" for r in results),
    )
