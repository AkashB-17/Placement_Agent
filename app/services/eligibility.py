"""
Deterministic eligibility check. No LLM, no similarity search.

Every rule is evaluated independently and all failures are reported. A rule that is
None or an empty list means "not stated" and is not enforced. Branches and batches
are compared after the same normalization used at ingest, so older rows and
hand-typed values still compare correctly.
"""
from __future__ import annotations

from typing import Any

from app.schemas import EligibilityResult, FailedRule, JDRequirements, PolicyRules
from app.services.normalize import normalize_batch, normalize_branch

# Natural-language descriptions double as retrieval queries for citations.
RULE_DESCRIPTIONS = {
    "min_cgpa": "minimum CGPA required to be eligible",
    "max_active_backlogs": "maximum number of active backlogs allowed",
    "allowed_branches": "branches eligible to apply",
    "allowed_batches": "graduating batches eligible to apply",
    "placed_students_can_apply": "whether already placed students can apply again",
}


def _fail(rule: str, source: str, student_value: Any, required_value: Any) -> FailedRule:
    return FailedRule(
        rule=rule,
        source=source,
        description=RULE_DESCRIPTIONS[rule],
        student_value=student_value,
        required_value=required_value,
    )


def _membership_failures(
    rule: str,
    student_value: str,
    allowed_by_source: dict[str, list[str]],
    normalizer,
) -> list[FailedRule]:
    failures = []
    normalized_value = normalizer(student_value).casefold()
    for source, allowed in allowed_by_source.items():
        if not allowed:
            continue
        if normalized_value not in {normalizer(item).casefold() for item in allowed}:
            failures.append(_fail(rule, source, student_value, allowed))
    return failures


def check_eligibility(
    student: dict[str, Any],
    policy: PolicyRules,
    jd: JDRequirements,
) -> EligibilityResult:
    """`student` needs cgpa, active_backlogs, branch, batch and is_placed."""
    failed: list[FailedRule] = []

    # CGPA: the stricter of the policy minimum and the JD override applies.
    cgpa_floors = {
        source: value
        for source, value in (("policy", policy.min_cgpa), ("jd", jd.min_cgpa_override))
        if value is not None
    }
    if cgpa_floors:
        source, floor = max(cgpa_floors.items(), key=lambda item: item[1])
        if student["cgpa"] < floor:
            failed.append(_fail("min_cgpa", source, student["cgpa"], floor))

    if policy.max_active_backlogs is not None and student["active_backlogs"] > policy.max_active_backlogs:
        failed.append(
            _fail("max_active_backlogs", "policy", student["active_backlogs"], policy.max_active_backlogs)
        )

    failed += _membership_failures(
        "allowed_branches",
        student["branch"],
        {"policy": policy.allowed_branches, "jd": jd.allowed_branches},
        normalize_branch,
    )
    failed += _membership_failures(
        "allowed_batches",
        student["batch"],
        {"policy": policy.allowed_batches, "jd": jd.allowed_batches},
        normalize_batch,
    )

    if student.get("is_placed") and policy.placed_students_can_apply is False:
        failed.append(_fail("placed_students_can_apply", "policy", True, False))

    return EligibilityResult(eligible=not failed, failed_rules=failed)
