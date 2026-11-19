"""
Import generated students (the Gemini JSON) into the layout scripts/seed_sample.py-style
loaders use, plus an answer key, and sanity-check it.

    uv run python scripts/import_student_bundle.py data/generated/students_raw_batch1.json

Writes (merged by id, so later batches add to them):
    data/generated/students/resumes/<id>_<name>.txt
    data/generated/students/students.json     # profile fields + resume file name
    data/generated/students_answer_key.json   # true skills, traps, decoy mentions

Checks printed per student:
* a true skill that does not appear in the resume text (Gemini labelled a paraphrase as true);
* "decoy mentions": skills from the JD answer key that appear in the resume but are NOT
  true skills (negated, "currently learning", hobbies). The scorer should reject these;
* branches the app cannot normalise.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.normalize import _known_branch  # noqa: E402

OUT_DIR = ROOT / "data" / "generated" / "students"
RESUME_DIR = OUT_DIR / "resumes"
STUDENTS_PATH = OUT_DIR / "students.json"
KEY_PATH = ROOT / "data" / "generated" / "students_answer_key.json"
JD_KEY_PATH = ROOT / "data" / "generated" / "jds_answer_key.json"
PROFILE_FIELDS = ("name", "email", "branch", "batch", "cgpa", "active_backlogs", "is_placed")


def mentions(skill: str, text: str) -> bool:
    """Whole-word, case-insensitive: "Java" does not match inside "JavaScript"."""
    pattern = r"(?<![A-Za-z0-9])" + re.escape(skill) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a generated student bundle.")
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    students = json.loads(args.bundle.read_text(encoding="utf-8"))

    jd_skills: set[str] = set()
    if JD_KEY_PATH.exists():
        for jd in json.loads(JD_KEY_PATH.read_text(encoding="utf-8")):
            jd_skills.update(jd["required_skills"] + jd["preferred_skills"])

    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    seed = {s["id"]: s for s in json.loads(STUDENTS_PATH.read_text(encoding="utf-8"))} if STUDENTS_PATH.exists() else {}
    key = {k["id"]: k for k in json.loads(KEY_PATH.read_text(encoding="utf-8"))} if KEY_PATH.exists() else {}

    issues = 0
    for s in students:
        file = f"{s['id']}_{slug(s['name'])}.txt"
        text = s["resume_text"]
        (RESUME_DIR / file).write_text(text.rstrip() + "\n", encoding="utf-8")
        seed[s["id"]] = {"id": s["id"], "file": file, **{f: s[f] for f in PROFILE_FIELDS}}

        unproven = [k for k in s["true_skills"] if not mentions(k, text)]
        decoys = sorted(k for k in jd_skills if k not in s["true_skills"] and mentions(k, text))
        key[s["id"]] = {
            "id": s["id"],
            "name": s["name"],
            "file": file,
            "true_skills": s["true_skills"],
            "traps": s["traps"],
            "decoy_mentions": decoys,
            "true_skills_not_verbatim": unproven,
        }

        words = len(text.split())
        notes = [f"{words} words"]
        if not _known_branch(s["branch"]):
            notes.append(f"UNKNOWN BRANCH {s['branch']!r}")
            issues += 1
        if unproven:
            notes.append(f"true skill not in resume text: {unproven}")
            issues += 1
        if decoys:
            notes.append(f"decoys: {decoys}")
        print(f"{s['id']}  {s['name']:18s} {', '.join(notes)}")

    STUDENTS_PATH.write_text(json.dumps(sorted(seed.values(), key=lambda r: r["id"]), indent=2) + "\n", encoding="utf-8")
    KEY_PATH.write_text(json.dumps(sorted(key.values(), key=lambda r: r["id"]), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"\n{len(students)} students imported -> {RESUME_DIR.relative_to(ROOT)} | "
        f"{len(seed)} in students.json | answer key {len(key)} entries | {issues} issue(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
