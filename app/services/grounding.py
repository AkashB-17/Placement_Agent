"""
Grounding checks for LLM-extracted eligibility rules.

Eligibility is deterministic, but its inputs come from LLM extraction. A hallucinated
rule would be enforced as if the policy said it, so before a rule is stored we check
that the source text actually supports it, and drop it (with a warning) otherwise.

Covered: batches (the year must appear in a sentence about batch/graduation, so an
application deadline in 2026 is not read as "batch 2026") and CGPA cutoffs (the number
must appear in the text). Branches and backlog limits are not grounded yet.
"""
from __future__ import annotations

import re

from app.schemas import JDRequirements, PolicyRules
from app.services.normalize import normalize_batch

_BATCH_KEYWORDS = re.compile(r"batch|graduat|pass[\s-]?out|year of passing|class of", re.IGNORECASE)
_YEAR_EXPR = re.compile(r"(?<!\d)\d{4}(?:\s*[-/]\s*\d{2,4})?(?!\d)")
_SENTENCE_SPLIT = re.compile(r"\n+|(?<=[.!?])\s+")


def _stated_batches(text: str) -> set[str]:
    years: set[str] = set()
    for sentence in _SENTENCE_SPLIT.split(text):
        if _BATCH_KEYWORDS.search(sentence):
            for expr in _YEAR_EXPR.findall(sentence):
                years.add(normalize_batch(expr))
                years.update(re.findall(r"\d{4}", expr))
    return years


def _number_in_text(value: float, text: str) -> bool:
    integer, _, decimals = f"{value:g}".partition(".")
    pattern = rf"(?<![\d.]){integer}" + (rf"\.{decimals}0*" if decimals else r"(?:\.0+)?") + r"(?!\.?\d)"
    return re.search(pattern, text) is not None


def _ground_batches(batches: list[str], text: str, warnings: list[str]) -> list[str]:
    stated = _stated_batches(text)
    kept = [batch for batch in batches if batch in stated]
    for batch in batches:
        if batch not in stated:
            warnings.append(f"Dropped allowed_batches '{batch}': not stated as a batch in the document.")
    return kept


def _ground_cgpa(value: float | None, field: str, text: str, warnings: list[str]) -> float | None:
    if value is not None and not _number_in_text(value, text):
        warnings.append(f"Dropped {field} {value}: number not found in the document.")
        return None
    return value


def ground_policy(rules: PolicyRules, text: str) -> list[str]:
    """Drop unsupported rules in place; return warnings."""
    warnings: list[str] = []
    rules.allowed_batches = _ground_batches(rules.allowed_batches, text, warnings)
    rules.min_cgpa = _ground_cgpa(rules.min_cgpa, "min_cgpa", text, warnings)
    return warnings


def ground_jd(requirements: JDRequirements, text: str) -> list[str]:
    """Drop unsupported rules in place; return warnings."""
    warnings: list[str] = []
    requirements.allowed_batches = _ground_batches(requirements.allowed_batches, text, warnings)
    requirements.min_cgpa_override = _ground_cgpa(
        requirements.min_cgpa_override, "min_cgpa_override", text, warnings
    )
    return warnings
