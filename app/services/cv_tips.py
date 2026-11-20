"""
CV improvement tips for one student and one job.

Code decides *what* is missing: the gaps are exactly the missing skills from the verified
score breakdown, never the LLM's opinion. The LLM only writes advice for those gaps, and
may point at a resume line showing related work. That quote goes through the same
verbatim check as scoring evidence; a quote that isn't really in the CV is dropped, and
the tip becomes "build" (gain the skill) instead of "surface" (show what you already did).

Tips never tell a student to claim a skill they don't have, and the CV is never edited:
the student decides what to change and uploads a new version themselves.

Results are cached in score_cache (same inputs → same tips, no repeat AI call).
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app import db
from app.config import get_settings
from app.schemas import CvTip, JDRequirements, ScoreBreakdown
from app.services.llm import extract_structured
from app.services.scoring import quote_in_resume

TIPS_VERSION = "1"
MAX_SUGGESTION_CHARS = 400


class _RawTip(BaseModel):
    skill: str
    related_quote: str | None = None
    suggestion: str


class _RawTips(BaseModel):
    tips: list[_RawTip] = Field(default_factory=list)


def _instructions(jd: JDRequirements, required: list[str], preferred: list[str], matched: list[str]) -> str:
    role = " at ".join(p for p in (jd.role, jd.company) if p) or "this job"
    return (
        f"You are a careers adviser. A student's resume follows. They are applying for {role}. "
        "Their resume does not show the skills listed below. For EACH listed skill, return one "
        "entry with the skill name exactly as written:\n"
        "- related_quote: if the resume describes related work that may genuinely involve the "
        "skill but doesn't name it, copy that span character-for-character from the resume "
        "(under 120 characters). Otherwise null. Never invent or reword quotes.\n"
        "- suggestion: 1-2 concrete sentences. If there is a related quote, say how to rewrite "
        "that line to make the skill visible, only if they actually used it. If not, suggest a "
        "small, specific way to gain and show the skill (a project, course or certification).\n"
        "Never advise claiming a skill the student has not used. Be specific to this job.\n\n"
        f"Missing required skills: {required}\n"
        f"Missing preferred skills: {preferred}\n"
        f"Skills the resume already shows: {matched}"
    )


def _cache_key(resume_text: str, instructions: str) -> str:
    payload = json.dumps(
        {
            "kind": "cv-tips",
            "version": TIPS_VERSION,
            "model": get_settings().openai_chat_model,
            "instructions": instructions,
            "resume_sha256": hashlib.sha256(resume_text.encode("utf-8")).hexdigest(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_tips(raw: _RawTips, required: list[str], preferred: list[str], resume_text: str) -> list[CvTip]:
    """Keep one tip per missing skill, in JD order (required first); verify every quote."""
    claims = {t.skill.strip().casefold(): t for t in raw.tips}
    tips: list[CvTip] = []
    for skill, is_required in [(s, True) for s in required] + [(s, False) for s in preferred]:
        claim = claims.get(skill.casefold())
        quote = (claim.related_quote or "").strip() if claim else ""
        verified = bool(quote) and quote_in_resume(quote, resume_text)
        suggestion = (claim.suggestion.strip() if claim else "")[:MAX_SUGGESTION_CHARS]
        if not suggestion:
            suggestion = f"Your CV doesn't show {skill}. If you've used it, add a line that says where and how."
        tips.append(
            CvTip(
                skill=skill,
                required=is_required,
                kind="surface" if verified else "build",
                related_quote=quote if verified else None,
                suggestion=suggestion,
            )
        )
    return tips


def cv_tips(
    student: dict[str, Any], jd: JDRequirements, jd_id: str, breakdown: ScoreBreakdown
) -> tuple[list[CvTip], str]:
    """(tips, "cache" | "fresh" | "none") for the skills the verified breakdown says are missing."""
    required, preferred = breakdown.missing_required, breakdown.missing_preferred
    if not required and not preferred:
        return [], "none"
    resume_text: str = student.get("resume_text") or ""
    instructions = _instructions(jd, required, preferred, breakdown.matched_required + breakdown.matched_preferred)
    key = _cache_key(resume_text, instructions)
    cached = db.get_cached_score(key)
    if cached is not None:
        return [CvTip(**t) for t in cached["tips"]], "cache"
    raw = extract_structured(resume_text, _RawTips, instructions)
    tips = build_tips(raw, required, preferred, resume_text)
    db.put_cached_score(
        key, student["id"], jd_id, get_settings().openai_chat_model,
        json.dumps({"tips": [t.model_dump() for t in tips]}), datetime.now(UTC),
    )
    return tips, "fresh"
