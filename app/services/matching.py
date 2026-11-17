"""
Evaluate students against a JD: eligibility first (deterministic), then scoring only for
eligible students, or citations of the clause behind each failed rule.

Shared by /match, /ranked and auto-apply so all three judge a student the same way.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import HTTPException

from app.config import get_settings
from app.db import get_jd, get_policy, get_student
from app.schemas import Citation, CitationChunk, FailedRule, JDRequirements, MatchResult, PolicyRules
from app.services.eligibility import check_eligibility
from app.services.scoring import score_student_cached
from app.services.vectorstore import COLLECTION_JDS, COLLECTION_POLICIES, retrieve

CITATION_K = 2
RANK_WORKERS = 8  # parallel OpenAI calls per batch evaluation


def load_policy(policy_id: str) -> PolicyRules:
    row = get_policy(policy_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found.")
    return PolicyRules(**row["rules"])


def load_jd(jd_id: str) -> JDRequirements:
    row = get_jd(jd_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"JD '{jd_id}' not found.")
    return JDRequirements(**row["requirements"])


def load_student(student_id: str) -> dict[str, Any]:
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
    refresh: bool = False,
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

    # Only the LLM-backed score is cached; eligibility above is always recomputed.
    breakdown, result.score_source = score_student_cached(student, jd, jd_id, refresh=refresh)
    result.score_breakdown = breakdown
    result.auto_apply_recommended = (
        breakdown.score is not None and breakdown.score >= get_settings().auto_apply_threshold
    )
    return result


def evaluate_many(
    students: list[dict[str, Any]],
    policy: PolicyRules,
    jd: JDRequirements,
    policy_id: str,
    jd_id: str,
    refresh: bool = False,
) -> list[MatchResult]:
    """Evaluate in parallel: each eligible student costs one independent OpenAI call.

    Results come back in the input order."""
    if not students:
        return []
    with ThreadPoolExecutor(max_workers=RANK_WORKERS) as pool:
        return list(pool.map(lambda s: evaluate_student(s, policy, jd, policy_id, jd_id, refresh), students))
