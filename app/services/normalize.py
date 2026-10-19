"""
Deterministic normalization of branch and batch values.

Eligibility compares branches and batches as strings, so every source (LLM-extracted
policy/JD rules and the student's own form fields) goes through the same functions
here. The extraction prompts also ask for these formats, but the prompt is a hint;
this module is what guarantees it.
"""
from __future__ import annotations

import re

# Keys are lowercase, "&" replaced by "and", punctuation collapsed to single spaces.
_BRANCH_ALIASES: dict[str, str] = {
    "cse": "CSE",
    "cs": "CSE",
    "computer science": "CSE",
    "computer science engineering": "CSE",
    "computer science and engineering": "CSE",
    "ece": "ECE",
    "ec": "ECE",
    "electronics and communication": "ECE",
    "electronics and communication engineering": "ECE",
    "electronics and communications engineering": "ECE",
    "eee": "EEE",
    "electrical and electronics engineering": "EEE",
    "electrical and electronic engineering": "EEE",
    "ee": "EE",
    "electrical engineering": "EE",
    "me": "ME",
    "mech": "ME",
    "mechanical": "ME",
    "mechanical engineering": "ME",
    "ce": "CE",
    "civil": "CE",
    "civil engineering": "CE",
    "it": "IT",
    "information technology": "IT",
    "ai ml": "AI-ML",
    "aiml": "AI-ML",
    "ai and ml": "AI-ML",
    "artificial intelligence and machine learning": "AI-ML",
    "cse ai ml": "AI-ML",
    "cse aiml": "AI-ML",
    "ds": "DS",
    "data science": "DS",
    "cse ds": "DS",
    "cse data science": "DS",
}

# Degree prefixes stripped before lookup ("B.Tech CSE" -> "cse").
_DEGREE_PREFIX = re.compile(r"^(b tech|btech|b e|be|m tech|mtech|bachelor of technology( in)?)\s+")
_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_SHORT_RANGE = re.compile(r"(?<!\d)(\d{4})\s*[-/]\s*(\d{2})(?!\d)")  # "2023-27"


def _branch_key(value: str) -> str:
    key = value.lower().replace("&", " and ")
    key = re.sub(r"[^a-z0-9]+", " ", key).strip()
    return _DEGREE_PREFIX.sub("", key)


def normalize_branch(value: str) -> str:
    """Map a branch name to its short code; unknown branches are upper-cased as-is."""
    stripped = value.strip()
    if not stripped:
        return stripped
    return _BRANCH_ALIASES.get(_branch_key(stripped), stripped.upper())


def normalize_batch(value: str) -> str:
    """Reduce a batch to its 4-digit graduation year ("2023-2027" -> "2027").

    Values without a 4-digit year are returned stripped and unchanged.
    """
    stripped = value.strip()
    short_range = _SHORT_RANGE.search(stripped)
    if short_range:
        start, end = short_range.groups()
        return start[:2] + end
    years = _YEAR.findall(stripped)
    return max(years) if years else stripped


def normalize_list(values: list[str], normalizer) -> list[str]:
    """Normalize, drop empties and de-duplicate while preserving order."""
    seen: dict[str, None] = {}
    for value in values:
        normalized = normalizer(value)
        if normalized:
            seen.setdefault(normalized, None)
    return list(seen)
