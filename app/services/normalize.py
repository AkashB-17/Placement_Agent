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
    "electronics and communications": "ECE",
    "electronics and comm": "ECE",  # "Electronics & Comm."
    "electronics communication": "ECE",
    "electronics and communication engineering": "ECE",
    "electronics and communications engineering": "ECE",
    "e and c": "ECE",  # "E&C"
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


_ENGG = re.compile(r"\b(engg|engr|eng)\b")
# Separators inside one compound value: "CSE/IT", "CSE, IT", "CSE or IT".
_BRANCH_SPLIT = re.compile(r"\s*(?:/|,|\bor\b)\s*", re.IGNORECASE)


def _branch_key(value: str) -> str:
    key = value.lower().replace("&", " and ")
    key = re.sub(r"[^a-z0-9]+", " ", key).strip()
    key = _ENGG.sub("engineering", key)
    return _DEGREE_PREFIX.sub("", key)


def _known_branch(value: str) -> str | None:
    return _BRANCH_ALIASES.get(_branch_key(value)) if value.strip() else None


def normalize_branch(value: str) -> str:
    """Map a branch name to its short code; unknown branches are upper-cased as-is."""
    stripped = value.strip()
    if not stripped:
        return stripped
    return _known_branch(stripped) or stripped.upper()


def expand_branches(value: str) -> list[str]:
    """One allowed-branches entry to branch codes, splitting compounds like "CSE/IT".

    A known name is never split ("AI/ML" stays AI-ML). A compound is split only if
    every part is a known branch ("B.Tech CSE/IT/ECE" -> CSE, IT, ECE); otherwise the
    value is kept whole, as before, rather than guessing."""
    whole = _known_branch(value)
    if whole:
        return [whole]
    parts = [p for p in _BRANCH_SPLIT.split(value.strip()) if p.strip()]
    if len(parts) > 1:
        codes = [_known_branch(p) for p in parts]
        if all(codes):
            return list(dict.fromkeys(codes))  # type: ignore[arg-type]
    normalized = normalize_branch(value)
    return [normalized] if normalized else []


# "All branches", "any branch", "B.Tech all streams", "open to all disciplines": no restriction.
_UNRESTRICTED = re.compile(
    r"^(?:open to )?(?:all|any)(?: eligible)? (?:branches|branch|streams|stream|disciplines|discipline|departments)"
    r"(?: (?:are |is )?(?:eligible|allowed|welcome)(?: to apply)?)?$"
    r"|^all$|^any$|^open to all(?: branches)?$"
)
# Indian placement shorthand for the computer + electronics/electrical family.
CIRCUIT_BRANCHES = ["CSE", "IT", "AI-ML", "DS", "ECE", "EEE", "EE"]
_CIRCUIT = re.compile(r"^(?:any |all )?circuit (?:branches|branch|streams|stream)$")


def is_unrestricted(value: str) -> bool:
    """True for values meaning "every branch is eligible" (stored as no rule at all)."""
    return bool(_UNRESTRICTED.match(_branch_key(value)))


def normalize_branches(values: list[str]) -> list[str]:
    """normalize_list for branches: expands compounds ("CSE/IT") and the "circuit branches"
    shorthand; returns [] (= no branch rule) if any entry means "all branches"."""
    if any(is_unrestricted(v) for v in values if v.strip()):
        return []
    seen: dict[str, None] = {}
    for value in values:
        codes = CIRCUIT_BRANCHES if _CIRCUIT.match(_branch_key(value)) else expand_branches(value)
        for code in codes:
            seen.setdefault(code, None)
    return list(seen)


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
