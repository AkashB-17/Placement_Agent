"""
Import a bundle of generated JDs (from the Gemini prompt) into .txt + .pdf files and an
answer key, and sanity-check the answer key against the JD text.

    uv run python scripts/import_jd_bundle.py data/generated/jds_raw_batch1.txt

Bundle format (what the prompt asks for):
    === JD 01 | file: jd_01_some_name === ...text... === END JD 01 ===
    === ANSWER KEY === [ {...}, ... ] === END ANSWER KEY ===

Writes data/generated/jds/<file>.txt and .pdf, and merges the key into
data/generated/jds_answer_key.json (by "file", so later batches add to it).
The text is tidied lightly (Markdown links unwrapped, header fields on their own lines);
the wording is not changed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from text_to_pdf import layout, render  # noqa: E402

from app.services.auto_apply import local_zone, parse_deadline  # noqa: E402
from app.services.pdf import text_from_upload  # noqa: E402

OUT_DIR = ROOT / "data" / "generated" / "jds"
KEY_PATH = ROOT / "data" / "generated" / "jds_answer_key.json"

_JD_BLOCK = re.compile(r"=== JD (\d+) \| file: (\S+) ===(.*?)=== END JD \1 ===", re.DOTALL)
_KEY_BLOCK = re.compile(r"=== ANSWER KEY ===(.*?)=== END ANSWER KEY ===", re.DOTALL)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://)?[^)]+\)")
_INLINE_FIELDS = re.compile(r"[ \t]+(?=(?:Website|Job Title|Job Type|Experience|Deadline):)")
_SECTION_LABELS = re.compile(r"(?m)^(About the Company:|Role Overview & Responsibilities:|Application Details:)[ \t]+")
_ALL_BRANCHES = re.compile(r"\ball\b", re.IGNORECASE)


def tidy(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text)
    text = _INLINE_FIELDS.sub("\n", text)
    text = _SECTION_LABELS.sub(r"\n\1\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def check_key(entry: dict, text: str) -> list[str]:
    """Answer-key claims that the JD text does not back up (likely Gemini mistakes)."""
    problems = []
    lowered = text.lower()
    for field in ("required_skills", "preferred_skills"):
        for skill in entry.get(field, []):
            if skill.lower() not in lowered:
                problems.append(f"{field}: '{skill}' not found verbatim in the JD")
    cgpa = entry.get("min_cgpa")
    if cgpa is not None and f"{cgpa:g}" not in text and f"{cgpa}" not in text:
        problems.append(f"min_cgpa {cgpa} is not stated in the JD")
    branches = entry.get("allowed_branches", [])
    if any(_ALL_BRANCHES.search(b) for b in branches):
        problems.append(f"allowed_branches {branches} means no restriction; the app treats that as [] (fixed below)")
    written, iso = entry.get("deadline_as_written"), entry.get("deadline_iso")
    parsed = parse_deadline(written)
    parsed_day = parsed.astimezone(local_zone()).date().isoformat() if parsed else None
    if parsed_day != iso:
        problems.append(f"deadline '{written}': answer key says {iso}, the app parses {parsed_day}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a generated JD bundle.")
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    raw = args.bundle.read_text(encoding="utf-8")

    blocks = _JD_BLOCK.findall(raw)
    key_match = _KEY_BLOCK.search(raw)
    if not blocks:
        print("No '=== JD NN | file: ... ===' blocks found.", file=sys.stderr)
        return 1
    key = {entry["file"]: entry for entry in json.loads(key_match.group(1))} if key_match else {}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = json.loads(KEY_PATH.read_text(encoding="utf-8")) if KEY_PATH.exists() else []
    merged = {entry["file"]: entry for entry in existing}

    failures = 0
    for number, name, body in blocks:
        text = tidy(body)
        entry = key.get(name)
        title = f"{entry['company']} – {entry['role']}" if entry else None
        (OUT_DIR / f"{name}.txt").write_text(text, encoding="utf-8")
        pdf = render(layout(text, title), title or name)
        (OUT_DIR / f"{name}.pdf").write_bytes(pdf)

        extracted = text_from_upload(f"{name}.pdf", pdf)
        missing = set(re.findall(r"[a-z0-9]+", text.lower())) - set(re.findall(r"[a-z0-9]+", extracted.lower()))
        status = "ok" if not missing else f"LOST WORDS: {', '.join(sorted(missing)[:8])}"
        failures += bool(missing)
        print(f"JD {number}  {name:34s} pdf {status}")

        if entry is None:
            print("        (no answer-key entry)")
            continue
        for problem in check_key(entry, text):
            print(f"        key check: {problem}")
        if any(_ALL_BRANCHES.search(b) for b in entry.get("allowed_branches", [])):
            entry = {**entry, "allowed_branches": [], "notes": f"{entry.get('notes', '')} (all branches -> [])".strip()}
        merged[name] = entry

    KEY_PATH.write_text(json.dumps(sorted(merged.values(), key=lambda e: e["file"]), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n{len(blocks)} JDs -> {OUT_DIR.relative_to(ROOT)}  |  answer key: {len(merged)} entries -> {KEY_PATH.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
