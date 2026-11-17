"""
Load the demo data in data/sample/ into a running API, rank every JD, and compare the
results with data/sample/expected_outcomes.txt.

Start the server first (uv run uvicorn app.main:app), then:
    uv run python scripts/seed_sample.py [--base-url http://127.0.0.1:8000] [--token <access token>]

Re-running is safe: ids are content hashes, so the same files upsert the same rows.
This makes real OpenAI calls (one per document, one per eligible student per JD).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"
POLICY_FILE = "Policy.txt"
# JD file -> section header prefix in expected_outcomes.txt
JD_FILES = {
    "jd_strong_fit.txt": "Backend Software Engineer",
    "jd_niche.txt": "Embedded Firmware Engineer",
    "jd_strict_cgpa.txt": "Data Scientist",
}
SCORE_TOLERANCE = 0.1
EXPECTED_LINE = re.compile(
    r"^(?P<name>[^-]+?) - (?P<status>ELIGIBLE|INELIGIBLE)(?:.*expected score = (?P<score>[\d.]+))?"
)


def _post_document(client: httpx.Client, path: str, file: Path) -> dict:
    response = client.post(path, files={"file": (file.name, file.read_bytes(), "text/plain")})
    response.raise_for_status()
    return response.json()


def parse_expected(text: str) -> dict[str, dict[str, tuple[bool, float | None]]]:
    """Return {section header: {student name: (eligible, expected score)}}."""
    sections: dict[str, dict[str, tuple[bool, float | None]]] = {}
    current: dict[str, tuple[bool, float | None]] | None = None
    for line in text.splitlines():
        line = line.strip()
        if any(line.startswith(prefix) for prefix in JD_FILES.values()):
            current = sections.setdefault(line, {})
            continue
        match = EXPECTED_LINE.match(line)
        if match and current is not None:
            score = float(match["score"]) if match["score"] else None
            current[match["name"].strip()] = (match["status"] == "ELIGIBLE", score)
    return sections


def _expected_for(sections, header_prefix: str):
    for header, rows in sections.items():
        if header.startswith(header_prefix):
            return rows
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--token",
        default=os.environ.get("PLACEMENT_TOKEN"),
        help="Officer/admin access token from scripts/get_token.py (or env PLACEMENT_TOKEN). "
        "Not needed when the server runs with DEV_AUTH_BYPASS=true.",
    )
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    with httpx.Client(base_url=args.base_url, timeout=180, headers=headers) as client:
        client.get("/health").raise_for_status()

        policy = _post_document(client, "/policies", SAMPLE_DIR / POLICY_FILE)
        policy_id = policy["id"]
        print(f"policy {policy_id}: {json.dumps(policy['rules'])}")
        for warning in policy["warnings"]:
            print(f"  WARNING {warning}")

        jd_ids: dict[str, str] = {}
        for jd_file in JD_FILES:
            jd = _post_document(client, "/jds", SAMPLE_DIR / jd_file)
            jd_ids[jd_file] = jd["id"]
            req = jd["requirements"]
            print(
                f"jd {jd['id']} {jd_file}: required={req['required_skills']} preferred={req['preferred_skills']} "
                f"branches={req['allowed_branches']} batches={req['allowed_batches']} "
                f"min_cgpa_override={req['min_cgpa_override']}"
            )
            for warning in jd["warnings"]:
                print(f"  WARNING {warning}")

        students = json.loads((SAMPLE_DIR / "students.json").read_text(encoding="utf-8"))
        for student in students:
            resume = SAMPLE_DIR / "resumes" / student["file"]
            form = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in student.items() if k != "file"}
            response = client.post(
                "/students", data=form, files={"resume": (resume.name, resume.read_bytes(), "text/plain")}
            )
            response.raise_for_status()
            profile = response.json()["profile"]
            print(f"student {response.json()['id']} {profile['name']}: {profile['branch']} {profile['batch']}")

        sections = parse_expected((SAMPLE_DIR / "expected_outcomes.txt").read_text(encoding="utf-8"))
        mismatches = 0
        for jd_file, header in JD_FILES.items():
            response = client.get(f"/jds/{jd_ids[jd_file]}/ranked", params={"policy_id": policy_id})
            response.raise_for_status()
            ranked = response.json()
            expected = _expected_for(sections, header)
            print(f"\n=== {header} ({jd_file})")

            for row in ranked["eligible"]:
                b = row["score_breakdown"]
                print(
                    f"  ELIGIBLE   {row['student_name']:<16} score={b['score']} "
                    f"auto_apply={row['auto_apply_recommended']} missing_required={b['missing_required']} "
                    f"matched_preferred={b['matched_preferred']}"
                )
            for row in ranked["ineligible"]:
                rules = "; ".join(
                    f"{f['rule']}[{f['source']}] {f['student_value']} vs {f['required_value']}"
                    for f in row["eligibility"]["failed_rules"]
                )
                first_chunk = row["citations"][0]["chunks"][0]["text"] if row["citations"] and row["citations"][0]["chunks"] else ""
                print(f"  INELIGIBLE {row['student_name']:<16} {rules}")
                print(f"             cites: {first_chunk[:110]!r}")

            actual = {r["student_name"]: (True, r["score_breakdown"]["score"]) for r in ranked["eligible"]}
            actual |= {r["student_name"]: (False, None) for r in ranked["ineligible"]}
            for name, (exp_eligible, exp_score) in expected.items():
                act_eligible, act_score = actual.get(name, (None, None))
                if act_eligible != exp_eligible:
                    mismatches += 1
                    print(f"  MISMATCH {name}: expected eligible={exp_eligible}, got {act_eligible}")
                elif exp_eligible and (act_score is None or abs(act_score - exp_score) > SCORE_TOLERANCE):
                    mismatches += 1
                    print(f"  MISMATCH {name}: expected score {exp_score}, got {act_score}")

        print(f"\n{mismatches} mismatch(es) against expected_outcomes.txt")
        return 1 if mismatches else 0


_STATUS_HINTS = {
    401: "Not signed in, or the token expired (they last ~1 hour). Get a fresh one with scripts/get_token.py "
    "in this same terminal, then re-run.",
    403: "Your account's role can't do this. Use an officer or admin account.",
    502: "The API couldn't reach OpenAI or Supabase Storage. Check the server log.",
    503: "The API can't reach the database or Supabase's auth keys. Check DATABASE_URL and your network.",
}


def run() -> int:
    """main() with plain-English errors instead of tracebacks (the token is never printed)."""
    try:
        return main()
    except httpx.ConnectError:
        print("Can't reach the API. Start it first: uv run uvicorn app.main:app", file=sys.stderr)
    except httpx.HTTPStatusError as exc:
        response = exc.response
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:200]
        print(f"{response.request.method} {response.request.url.path} failed ({response.status_code}): {detail}", file=sys.stderr)
        hint = _STATUS_HINTS.get(response.status_code)
        if hint:
            print(hint, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(run())
