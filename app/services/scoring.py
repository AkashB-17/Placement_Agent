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

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app import db
from app.config import get_settings
from app.schemas import JDRequirements, ScoreBreakdown, SkillQuote
from app.services.llm import extract_structured

REQUIRED_WEIGHT = 0.75
PREFERRED_WEIGHT = 0.25
# Quote fragments: split on "..." / ellipsis, and between sentences.
_FRAGMENT_SPLIT = re.compile(r"\.{3}|\u2026|(?<=[.!?])\s+")
_EDGE_PUNCTUATION = re.compile(r"^[\s\"'.,;:!?\-]+|[\s\"'.,;:!?\-]+$")
_STOPWORDS = {"a", "an", "and", "or", "of", "the", "in", "with", "for", "to", "on"}
# Spacing next to list/label punctuation is unreliable on both sides: PDF extraction often
# drops it ("Languages:Python, SQL") and LLMs often add it back ("Languages: Python, SQL").
_SPACE_AROUND_PUNCT = re.compile(r"\s*([:;,/|()\[\]•·])\s*")


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
        "the skill, and set evidence_quote to a contiguous span copied character-for-character "
        "from the resume (under 120 characters) that names the skill. A sentence fragment is "
        "fine; do not shorten, reword, join separate sentences, or add punctuation. Otherwise set evidenced=false and "
        "evidence_quote=null. Never invent quotes.\n\n"
        f"Skills: {skills}"
    )


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _skill_tokens(skill: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9+#]+", _normalize_text(skill))
    return [token for token in tokens if token not in _STOPWORDS]


def quote_in_resume(quote: str, resume_text: str) -> bool:
    """True if the quote is a verbatim span of the resume.

    Tolerated: case, whitespace, spacing next to list/label punctuation (": , ; / | •" and
    brackets, on either side), surrounding quote marks and edge punctuation (LLMs often
    end a truncated sentence with a period), and several verbatim sentences or
    "..."-joined fragments glued together, each of which must appear in order.
    The words themselves must match: reworded text still fails.
    """
    resume = _SPACE_AROUND_PUNCT.sub(r"\1", _normalize_text(resume_text))
    fragments = [_EDGE_PUNCTUATION.sub("", f) for f in _FRAGMENT_SPLIT.split(_normalize_text(quote))]
    fragments = [_SPACE_AROUND_PUNCT.sub(r"\1", f) for f in fragments if f]
    if not fragments:
        return False
    position = 0
    for fragment in fragments:
        found = resume.find(fragment, position)
        if found < 0:
            return False
        position = found + len(fragment)
    return True


def _lowercase_word_before(text: str, start: int) -> bool:
    """A lowercase word ends right before `start`: "with" in "withPython", "onGCPwithDocker".

    The lowercase run must begin a word (after a non-letter) or follow an acronym
    ("GCPwith"); a run that is the tail of a capitalised word ("Postgre" + "SQL",
    "My" + "SQL") doesn't count."""
    i = start
    while i > 0 and text[i - 1].islower():
        i -= 1
    if i == start:
        return False
    if i == 0 or not text[i - 1].isalpha():
        return True
    return text[i - 1].isupper() and i >= 2 and text[i - 2].isupper()


def _lowercase_word_after(text: str, end: int) -> bool:
    """A lowercase word starts right at `end`: "to" in "SQLto", "with" in "GCPwithDocker"."""
    return end < len(text) and text[end].islower()


def _glued_mention(quote: str, token: str, prefix_ok: bool) -> bool:
    """The token appears glued to a neighbouring word at a case change.

    PDF extraction often loses the spaces around styled (bold) words, giving "withPython",
    "theOpenAI", "onGCPwith", "SQLto", "twoMCPservers". A case change from a plain lowercase
    word is a reliable sign of a lost space; a capitalised neighbour is not, so "PostgreSQL"
    and "MySQL" still don't count as mentioning "SQL". Known limit: an acronym followed by
    lowercase letters inside one real word ("SQLite") also counts, since code can't tell it
    from "SQLto" without a dictionary; the LLM must still have claimed the skill."""
    target = token.rstrip("s") if prefix_ok else token
    lowered = quote.casefold()
    start = lowered.find(target)
    while start >= 0:
        end = start + len(target)
        segment = quote[start:end]
        before = quote[start - 1] if start > 0 else ""
        after = quote[end] if end < len(quote) else ""
        left_ok = not before.isalnum() or (segment[:1].isupper() and _lowercase_word_before(quote, start))
        right_ok = (
            prefix_ok
            or not (after.isalnum() or after in "+#")
            or (segment[-1:].isupper() and _lowercase_word_after(quote, end))
        )
        if left_ok and right_ok:
            return True
        start = lowered.find(target, start + 1)
    return False


def quote_mentions_skill(quote: str, skill: str) -> bool:
    """True if any token of the skill appears as a word in the quote.

    Tokens longer than 3 characters may match as a prefix with a trailing "s" dropped
    ("APIs" matches "API", "Docker" matches "Dockerized"); short tokens ("C", "Go", "R")
    must match a whole word. A word glued to its neighbour by PDF extraction counts when
    the join is a case change from a lowercase word ("withPython", "SQLto"); see
    _glued_mention.
    """
    normalized_quote = _normalize_text(quote)
    original = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", quote)).strip()
    for token in _skill_tokens(skill):
        if len(token) > 3:
            pattern = rf"(?<![a-z0-9]){re.escape(token.rstrip('s'))}"
        else:
            pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9+#])"
        if re.search(pattern, normalized_quote):
            return True
        if _glued_mention(original, token, prefix_ok=len(token) > 3):
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


# ── Cache ───────────────────────────────────────────────────────────────────

# Bump when the validation or score code above changes in a way that changes results.
# (Prompt and model changes are already part of the key.)
SCORING_VERSION = "2"  # 2: spacing next to punctuation tolerated; words glued by PDF extraction ("withPython") recognised


def score_cache_key(resume_text: str, jd: JDRequirements) -> str | None:
    """Hash of every input the score depends on; None when no LLM call is needed."""
    required = _dedupe(jd.required_skills)
    preferred = _dedupe(jd.preferred_skills, exclude={s.casefold() for s in required})
    if not required:
        return None
    payload = json.dumps(
        {
            "version": SCORING_VERSION,
            "model": get_settings().openai_chat_model,
            "instructions": _evidence_instructions(required + preferred),
            "resume_sha256": hashlib.sha256(resume_text.encode("utf-8")).hexdigest(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def score_student_cached(
    student: dict[str, Any], jd: JDRequirements, jd_id: str, refresh: bool = False
) -> tuple[ScoreBreakdown, str]:
    """score_student with a database cache. Returns (breakdown, "cache" | "fresh" | "none").

    The cached value is the *verified* breakdown (quotes already checked against the
    resume), so a cache hit is exactly what a fresh call would have produced at that time.
    refresh=True re-scores and overwrites."""
    key = score_cache_key(student.get("resume_text") or "", jd)
    if key is None:
        return score_student(student, jd), "none"
    if not refresh:
        cached = db.get_cached_score(key)
        if cached is not None:
            return ScoreBreakdown(**cached), "cache"
    breakdown = score_student(student, jd)
    db.put_cached_score(
        key, student["id"], jd_id, get_settings().openai_chat_model,
        breakdown.model_dump_json(), datetime.now(UTC),
    )
    return breakdown, "fresh"
