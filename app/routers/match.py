"""
POST /match and GET /jds/{jd_id}/ranked.

Both endpoints share evaluate_student: eligibility first (deterministic), then scoring
only for eligible students, or citations of the clause behind each failed rule.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.db import get_all_students, get_jd, get_policy, get_student
from app.schemas import (
    Citation,
    CitationChunk,
    FailedRule,
    JDRequirements,
    MatchRequest,
    MatchResult,
    PolicyRules,
    RankedResponse,
)
from app.services.eligibility import check_eligibility
from app.services.scoring import score_student
from app.services.vectorstore import COLLECTION_JDS, COLLECTION_POLICIES, retrieve

router = APIRouter(tags=["match"])

CITATION_K = 2


def _load_policy(policy_id: str) -> PolicyRules:
    row = get_policy(policy_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found.")
    return PolicyRules(**row["rules"])


def _load_jd(jd_id: str) -> JDRequirements:
    row = get_jd(jd_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"JD '{jd_id}' not found.")
    return JDRequirements(**row["requirements"])


def _load_student(student_id: str) -> dict[str, Any]:
    row = get_student(student_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found.")
    return row


def _cite(rule: FailedRule, policy_id: str, jd_id: str) -> Citation:
    """Retrieve the clause behind a failed rule from the document the rule came from."""
    if rule.source == "jd":
        collection, source_id = COLLECTION_JDS, jd_id
    else:
        collection, source_id = COLLECTION_POLICIES, policy_id
    hits = retrieve(collection, query=rule.description, k=CITATION_K, where={"doc_id": source_id})
    return Citation(
        rule=rule.rule,
        source=rule.source,
        source_id=source_id,
        chunks=[CitationChunk(text=hit["text"], distance=hit["distance"]) for hit in hits],
    )


def evaluate_student(
    student: dict[str, Any],
    policy: PolicyRules,
    jd: JDRequirements,
    policy_id: str,
    jd_id: str,
) -> MatchResult:
    eligibility = check_eligibility(student, policy, jd)
    result = MatchResult(
        student_id=student["id"],
        student_name=student.get("name", ""),
        eligibility=eligibility,
        score_breakdown=None,
        auto_apply_recommended=False,
    )
    if not eligibility.eligible:
        result.citations = [_cite(rule, policy_id, jd_id) for rule in eligibility.failed_rules]
        return result

    breakdown = score_student(student, jd)
    result.score_breakdown = breakdown
    result.auto_apply_recommended = (
        breakdown.score is not None and breakdown.score >= get_settings().auto_apply_threshold
    )
    return result


@router.post("/match", response_model=MatchResult)
def match(body: MatchRequest) -> MatchResult:
    policy = _load_policy(body.policy_id)
    jd = _load_jd(body.jd_id)
    student = _load_student(body.student_id)
    return evaluate_student(student, policy, jd, body.policy_id, body.jd_id)


@router.get("/jds/{jd_id}/ranked", response_model=RankedResponse)
def ranked(
    jd_id: str,
    policy_id: str = Query(..., description="Policy ID to evaluate against"),
) -> RankedResponse:
    policy = _load_policy(policy_id)
    jd = _load_jd(jd_id)

    results = [evaluate_student(s, policy, jd, policy_id, jd_id) for s in get_all_students()]
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
        auto_apply_threshold=get_settings().auto_apply_threshold,
        eligible=eligible,
        ineligible=ineligible,
    )
