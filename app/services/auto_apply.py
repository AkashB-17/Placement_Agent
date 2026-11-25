"""
Staged auto-apply.

An officer runs auto-apply for a JD. For each student who opted in, deterministic checks
come first (already applied, excluded company, policy application limit), then the same
evaluation as /ranked (eligibility, then evidence-based score). A student who is eligible
and scores at or above max(college threshold, their own bar) gets a PENDING application
pinned to the resume version and score evidence of that moment, plus a notification.

Nothing reaches the company until release_at = min(now + withdraw window, JD deadline -
buffer). Until then the student can withdraw. Release is one conditional UPDATE in the
database (see db.release_due_applications), run by a periodic sweep and before every read
of applications, so a late sweep never shows a stale status.

The LLM's only role here is the per-skill evidence inside scoring; whether to apply is
decided by code from the score, the rules and the student's preferences.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from app import db
from app.config import get_settings
from app.schemas import ApplicationOut, AutoApplyRun, JDRequirements, PolicyRules, ScoreBreakdown, SkippedStudent
from app.services.highlights import build_highlights, skill_highlights
from app.services.eligibility import check_eligibility
from app.services.matching import evaluate_many, evaluate_student, load_jd, load_policy

logger = logging.getLogger("uvicorn.error")

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
)
_ORDINAL = re.compile(r"\b(\d{1,2})(st|nd|rd|th)\b", re.IGNORECASE)
_WEEKDAY = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+", re.IGNORECASE)


def utcnow() -> datetime:
    """The clock. Tests replace it to move time forward."""
    return datetime.now(UTC)


def local_zone() -> timezone:
    return timezone(timedelta(minutes=get_settings().deadline_utc_offset_minutes))


def parse_deadline(text: str | None) -> datetime | None:
    """Parse a JD deadline like "November 20, 2026" or "2026-11-20" deterministically.

    A date without a time means the end of that day in the college's time zone, including
    its last second (23:59:59.999999), so a student can apply until the day is over. Anything
    unrecognised returns None: the run then relies on the withdraw window alone."""
    if not text:
        return None
    cleaned = text.strip().rstrip(".")
    try:
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=local_zone())
        if len(cleaned) <= 10:  # date only
            parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        return parsed.astimezone(UTC)
    except ValueError:
        pass
    cleaned = _WEEKDAY.sub("", _ORDINAL.sub(r"\1", cleaned)).replace(",", " ")
    cleaned = " ".join(cleaned.split())
    for fmt in _DATE_FORMATS:
        try:
            day = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        return day.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=local_zone()).astimezone(UTC)
    return None


def release_time(now: datetime, deadline: datetime | None) -> tuple[datetime, datetime | None]:
    """(release_at, cutoff): the window end, pulled earlier by the deadline buffer if needed."""
    settings = get_settings()
    window_end = now + timedelta(hours=settings.auto_apply_withdraw_hours)
    cutoff = deadline - timedelta(hours=settings.auto_apply_deadline_buffer_hours) if deadline else None
    return (min(window_end, cutoff) if cutoff else window_end), cutoff


def format_local(moment: datetime) -> str:
    offset = get_settings().deadline_utc_offset_minutes
    sign = "+" if offset >= 0 else "-"
    hours, minutes = divmod(abs(offset), 60)
    return f"{moment.astimezone(local_zone()):%d %b %Y, %H:%M} (UTC{sign}{hours:02d}:{minutes:02d})"


def _job_label(company: str | None, role: str | None) -> str:
    return " – ".join(part for part in (company, role) if part) or "a job"


# ── Release ─────────────────────────────────────────────────────────────────

def release_due() -> list[str]:
    """Submit applications whose withdraw window has closed. Safe to call anytime."""
    return db.release_due_applications(
        utcnow(),
        lambda jd: f"Your application to {_job_label(jd['company'], jd['role'])} has been sent to the company.",
    )


def release_due_quietly() -> None:
    """For the background sweep: a failed sweep is logged and retried next tick."""
    try:
        released = release_due()
        if released:
            logger.info("Auto-apply: released %d application(s)", len(released))
    except Exception:
        logger.exception("Auto-apply release sweep failed")


# ── Applications out ────────────────────────────────────────────────────────

def to_out(application: dict[str, Any], now: datetime | None = None) -> ApplicationOut:
    now = now or utcnow()
    breakdown = ScoreBreakdown(**{k: v for k, v in application["match"].items() if k != "highlights"})
    return ApplicationOut(
        id=application["id"],
        student_id=application["student_id"],
        student_name=application["student_name"],
        jd_id=application["jd_id"],
        company=application["company"],
        role=application["role"],
        policy_id=application["policy_id"],
        status=application["status"],
        score=application["score"],
        score_breakdown=breakdown,
        # Older applications predate the snapshot: fall back to the skill lines.
        highlights=application["match"].get("highlights") or skill_highlights(breakdown),
        created_at=application["created_at"],
        release_at=application["release_at"],
        decided_at=application["decided_at"],
        can_withdraw=application["status"] == "pending" and application["release_at"] > now,
        has_resume_file=bool(application["resume_path"]),
        source=application["source"],
    )


# ── Run ─────────────────────────────────────────────────────────────────────

def application_window(
    jd: JDRequirements, now: datetime, manual: bool = False
) -> tuple[datetime | None, datetime, datetime | None]:
    """(deadline, release_at, cutoff) for an application made now, or 409 if too late.

    Normally release_at = min(now + withdraw window, deadline - buffer), and auto-apply
    refuses when that leaves under auto_apply_min_window_minutes: the system is acting for
    the student, so they must have time to say no.

    A student applying themselves (manual=True) chose to apply, so it is accepted until
    the deadline itself. If the normal window doesn't fit, it is sent at the "last call",
    manual_apply_last_call_minutes before the deadline, and can be withdrawn until then;
    inside the last call it is sent straight away (one second later: the database requires
    release_at > created_at, and every read releases due applications)."""
    settings = get_settings()
    deadline = parse_deadline(jd.deadline)
    release_at, cutoff = release_time(now, deadline)
    if deadline is not None and deadline <= now:
        raise HTTPException(status_code=409, detail=f"The application deadline ({format_local(deadline)}) has passed.")
    min_window = timedelta(minutes=settings.auto_apply_min_window_minutes)
    if release_at - now >= min_window:
        return deadline, release_at, cutoff

    when = format_local(deadline) if deadline else "unknown"
    if manual and deadline is not None:
        last_call = deadline - timedelta(minutes=settings.manual_apply_last_call_minutes)
        release_at = min(max(last_call, now + timedelta(seconds=1)), deadline)
        return deadline, release_at, last_call
    raise HTTPException(
        status_code=409,
        detail=(
            f"Too close to the application deadline ({when}): students would have less than "
            f"{settings.auto_apply_min_window_minutes:g} minutes to withdraw."
        ),
    )


def _new_application(
    student: dict[str, Any], jd_id: str, policy_id: str, policy: PolicyRules, jd: JDRequirements,
    breakdown: ScoreBreakdown, now: datetime, release_at: datetime, actor_id: str | None,
) -> dict[str, Any]:
    # The snapshot: score evidence plus the code-built "why they stand out" lines.
    snapshot = {**breakdown.model_dump(mode="json"), "highlights": build_highlights(student, policy, jd, breakdown)}
    return {
        "id": uuid.uuid4().hex,
        "student_id": student["id"],
        "jd_id": jd_id,
        "policy_id": policy_id,
        "score": breakdown.score,
        "match_json": json.dumps(snapshot),
        # The resume as scored: content-addressed file path (never overwritten) and text hash.
        "resume_path": student["resume_path"],
        "resume_sha": hashlib.sha256(student["resume_text"].encode("utf-8")).hexdigest(),
        "created_at": now,
        "release_at": release_at,
        "created_by": actor_id,
    }


def apply_manually(student: dict[str, Any], jd_id: str, policy_id: str, actor_id: str | None) -> ApplicationOut:
    """A student applies to one job from their job board.

    Same pipeline as auto-apply (deterministic eligibility, evidence-based score snapshot,
    pinned CV, pending with a withdraw window, then release), minus the score bar and the
    excluded-companies preference: the student chose this job themselves.

    A student may re-apply to a job they withdrew from (while it is still open): the same
    application goes back to pending with a fresh snapshot and a new withdraw window.
    Auto-apply never does this; only the student's own click can."""
    release_due()
    policy = load_policy(policy_id)
    jd = load_jd(jd_id)
    existing = db.application_statuses_for_jd(jd_id).get(student["id"])
    reapplying = existing == "withdrawn"
    if existing and not reapplying:
        raise HTTPException(status_code=409, detail=f"You already have a {existing} application for this job.")
    now = utcnow()
    _, release_at, _ = application_window(jd, now, manual=True)
    if not (student.get("resume_text") or "").strip():
        raise HTTPException(status_code=409, detail="Upload your CV under Profile & CV before applying.")
    limit = policy.max_applications_per_student
    if limit is not None and db.active_application_counts().get(student["id"], 0) >= limit:
        raise HTTPException(status_code=409, detail=f"You've reached the policy limit of {limit} active applications.")

    eligibility = check_eligibility(student, policy, jd)  # rules first: no AI call if ineligible
    if not eligibility.eligible:
        failed = "; ".join(rule.description for rule in eligibility.failed_rules)
        raise HTTPException(status_code=409, detail=f"You're not eligible for this job: {failed}.")
    breakdown = evaluate_student(student, policy, jd, policy_id, jd_id).score_breakdown
    if breakdown is None or breakdown.score is None:
        raise HTTPException(
            status_code=409,
            detail="This job lists no required skills, so it can't be scored. Contact the placement office.",
        )

    application = _new_application(student, jd_id, policy_id, policy, jd, breakdown, now, release_at, actor_id)
    message = (
        f"You {'re-applied' if reapplying else 'applied'} to {_job_label(jd.company, jd.role)} "
        f"(score {breakdown.score:.1f}). It will be sent on {format_local(release_at)}. "
        "Withdraw before then if you change your mind."
    )
    if reapplying:
        application_id = db.reapply_application(application, message)
    else:
        application_id = application["id"] if db.create_application(application, message) else None
    if application_id is None:  # another request changed it in between
        raise HTTPException(status_code=409, detail="Your application for this job changed just now. Refresh and try again.")
    return to_out(db.get_application(application_id), now)


def run_auto_apply(jd_id: str, policy_id: str, actor_id: str | None) -> AutoApplyRun:
    settings = get_settings()
    release_due()  # statuses and application counts must be current before deciding
    policy = load_policy(policy_id)
    jd = load_jd(jd_id)

    now = utcnow()
    deadline, release_at, cutoff = application_window(jd, now)

    opted_in = db.list_opted_in_students()
    total_students = len(db.list_students())
    existing = db.application_statuses_for_jd(jd_id)
    active = db.active_application_counts()
    company_key = (jd.company or "").strip().casefold()

    skipped: list[SkippedStudent] = []
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for student, prefs in opted_in:
        reason = None
        if student["id"] in existing:
            reason = f"Already has a {existing[student['id']]} application for this job (never sent twice)."
        elif not (student.get("resume_text") or "").strip():
            reason = "Has not uploaded a CV yet."
        elif company_key and company_key in {c.strip().casefold() for c in prefs["excluded_companies"]}:
            reason = "Excluded this company in their auto-apply preferences."
        elif (
            policy.max_applications_per_student is not None
            and active.get(student["id"], 0) >= policy.max_applications_per_student
        ):
            reason = f"Reached the policy limit of {policy.max_applications_per_student} active applications."
        if reason:
            skipped.append(SkippedStudent(student_id=student["id"], student_name=student["name"], reason=reason))
        else:
            candidates.append((student, prefs))

    results = evaluate_many([s for s, _ in candidates], policy, jd, policy_id, jd_id)

    created: list[ApplicationOut] = []
    for (student, prefs), result in zip(candidates, results):
        breakdown = result.score_breakdown
        bar = max(settings.auto_apply_threshold, prefs["min_score"])
        reason = None
        if not result.eligibility.eligible:
            failed = "; ".join(rule.description for rule in result.eligibility.failed_rules)
            reason = f"Not eligible: {failed}."
        elif breakdown is None or breakdown.score is None:
            reason = "The JD lists no required skills, so there is no score to apply on."
        elif breakdown.score < bar:
            reason = f"Score {breakdown.score:.1f} is below their bar of {bar:g}."
        if reason:
            skipped.append(SkippedStudent(student_id=student["id"], student_name=student["name"], reason=reason))
            continue

        application = _new_application(student, jd_id, policy_id, policy, jd, breakdown, now, release_at, actor_id)
        message = (
            f"We applied to {_job_label(jd.company, jd.role)} for you (score {breakdown.score:.1f}). "
            f"It will be sent on {format_local(release_at)}. Withdraw before then if you don't want to apply."
        )
        if not db.create_application(application, message):
            skipped.append(
                SkippedStudent(student_id=student["id"], student_name=student["name"], reason="Applied by another run just now.")
            )
            continue
        stored = db.get_application(application["id"])
        if stored is not None:
            created.append(to_out(stored, now))

    return AutoApplyRun(
        jd_id=jd_id,
        policy_id=policy_id,
        deadline=deadline,
        release_cutoff=cutoff,
        release_at=release_at,
        created=created,
        skipped=sorted(skipped, key=lambda s: s.student_name),
        not_opted_in=max(total_students - len(opted_in), 0),
    )
