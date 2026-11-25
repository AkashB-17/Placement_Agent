"""
"Why this candidate stands out": short, factual lines for recruiters and officers.

Built entirely in code from facts the pipeline already established: the verified score
breakdown (every matched skill has a CV quote that code checked) and the academic record
the eligibility rules used. No LLM, so nothing here can be invented. The lines are saved
with the application (inside its match snapshot), so they describe the candidate as they
were when the application was made, like the score and pinned CV.
"""
from __future__ import annotations

from typing import Any

from app.schemas import JDRequirements, PolicyRules, ScoreBreakdown

MAX_NAMED_SKILLS = 4


def _names(skills: list[str]) -> str:
    shown = skills[:MAX_NAMED_SKILLS]
    more = len(skills) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more else "")


def skill_highlights(breakdown: ScoreBreakdown) -> list[str]:
    """Skill coverage lines. Usable on their own for applications made before highlights existed."""
    lines: list[str] = []
    matched, missing = breakdown.matched_required, breakdown.missing_required
    total = len(matched) + len(missing)
    if total:
        if not missing:
            lead = "the required skill" if total == 1 else f"all {total} required skills"
            lines.append(f"Shows {lead} in their CV: {_names(matched)}")
        elif matched:
            lines.append(f"Shows {len(matched)} of {total} required skills in their CV: {_names(matched)}")
    if breakdown.matched_preferred:
        lines.append(f"Also shows preferred skills: {_names(breakdown.matched_preferred)}")
    return lines


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def build_highlights(
    student: dict[str, Any], policy: PolicyRules, jd: JDRequirements, breakdown: ScoreBreakdown
) -> list[str]:
    lines = skill_highlights(breakdown)

    cgpa = student.get("cgpa")
    if cgpa is not None:
        floors = [v for v in (policy.min_cgpa, jd.min_cgpa_override) if v is not None]
        if floors:
            floor = max(floors)  # the same "stricter wins" rule eligibility uses
            margin = cgpa - floor
            lines.append(
                f"CGPA {_fmt(cgpa)}, {_fmt(margin)} above the required {_fmt(floor)}"
                if margin > 0 else f"CGPA {_fmt(cgpa)}, meets the required {_fmt(floor)}"
            )
        else:
            lines.append(f"CGPA {_fmt(cgpa)}")

    if student.get("active_backlogs") == 0:
        lines.append("No active backlogs")
    return lines
