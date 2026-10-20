"""
Skill-coverage scoring. The LLM only reports per-skill evidence; the score is computed here.

Anti-hallucination checks applied in code to every LLM claim:
1. The skill list comes from the JD, not the LLM. A skill the LLM omits or renames is
   counted as missing, so omissions can never inflate coverage.
2. The quote must appear in the resume text (case-insensitive, whitespace-collapsed,
   so PDF line breaks don't reject real quotes).
3. The quote must mention the skill (a token-level heuristic), so a real but unrelated
   sentence such as "Python developer" is not accepted as evidence for "Rust".
Check 3 is a heuristic: it can reject paraphrased evidence ("built RESTful services"
for "API design"). That errs toward under-scoring, which is the safer failure for
an auto-apply threshold.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field

from app.schemas import JDRequirements, ScoreBreakdown, SkillQuote
from app.services.llm import extract_structured

REQUIRED_WEIGHT = 0.75
PREFERRED_WEIGHT = 0.25
_STOPWORDS = {"a", "an", "and", "or", "of", "the", "in", "with", "for", "to", "on"}


class SkillEvidence(BaseModel):
    skill: str
    evidenced: bool
    evidence_quote: str | None = None


class EvidenceReport(BaseModel):
    skills: list[SkillEvidence] = Field(default_factory=list)


def _evidence_instructions(skills: list[str]) -> str:
    return (
        "You are given a student's resume. For EACH skill listed below, return one entry "
        "with the skill name exactly as written. Set evidenced=true only if the resume shows "
        "the skill, and copy a short verbatim excerpt (under 120 characters) that mentions it "
        "into evidence_quote. Otherwise set evidenced=false and evidence_quote=null. "
        "Never paraphrase or invent quotes.\n\n"
        f"Skills: {skills}"
    )


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _skill_tokens(skill: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9+#]+", _normalize_text(skill))
    return [token for token in tokens if token not in _STOPWORDS]


def quote_in_resume(quote: str, resume_text: str) -> bool:
    normalized_quote = _normalize_text(quote)
    return bool(normalized_quote) and normalized_quote in _normalize_text(resume_text)


def quote_mentions_skill(quote: str, skill: str) -> bool:
    """True if any token of the skill appears as a word in the quote.

    Tokens longer than 3 characters may match as a prefix with a trailing "s" dropped
    ("APIs" matches "API", "Docker" matches "Dockerized"); short tokens ("C", "Go", "R")
    must match a whole word.
    """
    normalized_quote = _normalize_text(quote)
    for token in _skill_tokens(skill):
        if len(token) > 3:
            pattern = rf"(?<![a-z0-9]){re.escape(token.rstrip('s'))}"
        else:
            pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9+#])"
        if re.search(pattern, normalized_quote):
            return True
    return False


def validate_evidence(item: SkillEvidence, resume_text: str) -> SkillQuote | None:
    """Return the accepted evidence for a skill, or None if the claim fails any check."""
    if not item.evidenced or not item.evidence_quote:
        return None
    if not quote_in_resume(item.evidence_quote, resume_text):
        return None
    if not quote_mentions_skill(item.evidence_quote, item.skill):
        return None
    return SkillQuote(skill=item.skill, quote=item.evidence_quote.strip())


def compute_score(required_coverage: float | None, preferred_coverage: float | None) -> float | None:
    if required_coverage is None:
        return None
    if preferred_coverage is None:
        return round(100 * required_coverage, 2)
    return round(100 * (REQUIRED_WEIGHT * required_coverage + PREFERRED_WEIGHT * preferred_coverage), 2)


def _dedupe(skills: list[str], exclude: set[str] = frozenset()) -> list[str]:
    seen: dict[str, str] = {}
    for skill in skills:
        key = skill.strip().casefold()
        if key and key not in exclude:
            seen.setdefault(key, skill.strip())
    return list(seen.values())


def score_student(student: dict[str, Any], jd: JDRequirements) -> ScoreBreakdown:
    """Score an (already eligible) student against a JD using the full resume text."""
    required = _dedupe(jd.required_skills)
    preferred = _dedupe(jd.preferred_skills, exclude={s.casefold() for s in required})
    if not required:
        return ScoreBreakdown(score=None, missing_preferred=preferred)

    resume_text: str = student.get("resume_text") or ""
    report = extract_structured(resume_text, EvidenceReport, _evidence_instructions(required + preferred))

    # Index LLM claims by skill name; anything not claimed counts as missing.
    claims = {item.skill.strip().casefold(): item for item in report.skills}
    accepted: dict[str, SkillQuote] = {}
    for skill in required + preferred:
        claim = claims.get(skill.casefold())
        if claim is None:
            continue
        claim = SkillEvidence(skill=skill, evidenced=claim.evidenced, evidence_quote=claim.evidence_quote)
        evidence = validate_evidence(claim, resume_text)
        if evidence is not None:
            accepted[skill] = evidence

    matched_required = [s for s in required if s in accepted]
    matched_preferred = [s for s in preferred if s in accepted]
    score = compute_score(
        len(matched_required) / len(required),
        len(matched_preferred) / len(preferred) if preferred else None,
    )
    return ScoreBreakdown(
        score=score,
        matched_required=matched_required,
        missing_required=[s for s in required if s not in accepted],
        matched_preferred=matched_preferred,
        missing_preferred=[s for s in preferred if s not in accepted],
        evidence=list(accepted.values()),
    )
