"""
Load the generated dataset (data/generated/) into a running API: the JD PDFs and the
students with their resumes. Nothing is ranked or evaluated; this only adds the data.

Start the API, get an officer/admin token, then:
    $env:PLACEMENT_TOKEN = uv run python scripts/get_token.py --email you@example.com   # PowerShell
    uv run python scripts/load_generated.py
    uv run python scripts/load_generated.py --dry-run      # check the files, upload nothing
    uv run python scripts/load_generated.py --jds "jd_2*" --skip-students   # only some JDs

Re-running is safe: ids are content hashes, so the same files update the same rows.
Makes one OpenAI call per JD (rule extraction) and one per student (resume parsing).
The JDs are checked against the existing policy at ranking time; no policy is uploaded.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

GENERATED = Path(__file__).resolve().parent.parent / "data" / "generated"
JD_DIR = GENERATED / "jds"
STUDENTS_FILE = GENERATED / "students" / "students.json"
RESUME_DIR = GENERATED / "students" / "resumes"
FORM_FIELDS = ("name", "email", "branch", "batch", "cgpa", "active_backlogs", "is_placed")

_HINTS = {
    401: "Not signed in or the token expired (~1 hour). Get a fresh one with scripts/get_token.py in this terminal.",
    403: "This account's role can't upload. Use an officer or admin account.",
    502: "The API couldn't reach OpenAI or Supabase Storage. Check the API log.",
    503: "The API can't reach the database. Check DATABASE_URL.",
}


def _jobs(pattern: str = "*") -> list[Path]:
    return sorted(JD_DIR.glob(f"{pattern}.pdf"))


def _students() -> list[dict]:
    return json.loads(STUDENTS_FILE.read_text(encoding="utf-8"))


def _form(student: dict) -> dict[str, str]:
    return {k: (str(student[k]).lower() if isinstance(student[k], bool) else str(student[k])) for k in FORM_FIELDS}


def dry_run(pattern: str = "*", skip_students: bool = False) -> int:
    jobs, students = _jobs(pattern), ([] if skip_students else _students())
    missing = [s["file"] for s in students if not (RESUME_DIR / s["file"]).exists()]
    print(f"{len(jobs)} JD PDFs in {JD_DIR.relative_to(GENERATED.parent.parent)} matching {pattern!r}")
    for pdf in jobs:
        print(f"  {pdf.stem}")
    print(f"{len(students)} students in {STUDENTS_FILE.relative_to(GENERATED.parent.parent)}; missing resumes: {missing or 'none'}")
    for s in students:
        form = _form(s)
        print(f"  {s['id']}  {form['name']:18s} {form['branch']:34s} batch {form['batch']}  cgpa {form['cgpa']:>4}  "
              f"backlogs {form['active_backlogs']}  placed {form['is_placed']}")
    return 1 if missing else 0


def load(base_url: str, token: str | None, pattern: str = "*", skip_students: bool = False) -> int:
    jobs, students = _jobs(pattern), ([] if skip_students else _students())
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=base_url, timeout=180, headers=headers) as client:
        client.get("/health").raise_for_status()

        for pdf in jobs:
            response = client.post("/jds", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
            response.raise_for_status()
            jd = response.json()
            req = jd["requirements"]
            print(f"JD   {pdf.stem:34s} -> {req['company']} | {req['role']} | branches {req['allowed_branches']} "
                  f"| batches {req['allowed_batches']} | cgpa {req['min_cgpa_override']} | deadline {req['deadline']}")
            for warning in jd["warnings"]:
                print(f"       WARNING {warning}")

        for student in students:
            resume = RESUME_DIR / student["file"]
            response = client.post(
                "/students",
                data=_form(student),
                files={"resume": (resume.name, resume.read_bytes(), "text/plain")},
            )
            response.raise_for_status()
            profile = response.json()["profile"]
            print(f"STU  {student['id']}  {profile['name']:18s} {profile['branch']:6s} {profile['batch']}  cgpa {profile['cgpa']}")

    print(f"\nLoaded {len(jobs)} JDs and {len(students)} students.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Load data/generated into a running API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.environ.get("PLACEMENT_TOKEN"))
    parser.add_argument("--dry-run", action="store_true", help="validate the files and print what would be loaded")
    parser.add_argument("--jds", default="*", help='only JD files matching this pattern, e.g. "jd_1[7-9]_*" or "jd_2*"')
    parser.add_argument("--skip-students", action="store_true", help="load JDs only")
    args = parser.parse_args()
    if args.dry_run:
        return dry_run(args.jds, args.skip_students)
    try:
        return load(args.base_url, args.token, args.jds, args.skip_students)
    except httpx.ConnectError:
        print(f"Can't reach the API at {args.base_url}. Start it first: uv run uvicorn app.main:app", file=sys.stderr)
    except httpx.HTTPStatusError as exc:
        response = exc.response
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:200]
        print(f"{response.request.method} {response.request.url.path} failed ({response.status_code}): {detail}", file=sys.stderr)
        if response.status_code in _HINTS:
            print(_HINTS[response.status_code], file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
