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
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from app import db
from app.config import get_settings
from app.schemas import ApplicationOut, AutoApplyRun, ScoreBreakdown, SkippedStudent
from app.services.matching import evaluate_many, load_jd, load_policy

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

    A date without a time means the end of that day in the college's time zone. Anything
    unrecognised returns None: the run then relies on the withdraw window alone."""
    if not text:
        return None
    cleaned = text.strip().rstrip(".")
    try:
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=local_zone())
        if len(cleaned) <= 10:  # date only
            parsed = parsed.replace(hour=23, minute=59, second=59)
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
        return day.replace(hour=23, minute=59, second=59, tzinfo=local_zone()).astimezone(UTC)
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
        score_breakdown=ScoreBreakdown(**application["match"]),
        created_at=application["created_at"],
        release_at=application["release_at"],
        decided_at=application["decided_at"],
        can_withdraw=application["status"] == "pending" and application["release_at"] > now,
        has_resume_file=bool(application["resume_path"]),
    )


# ── Run ─────────────────────────────────────────────────────────────────────

def run_auto_apply(jd_id: str, policy_id: str, actor_id: str | None) -> AutoApplyRun:
    settings = get_settings()
    release_due()  # statuses and application counts must be current before deciding
    policy = load_policy(policy_id)
    jd = load_jd(jd_id)

    now = utcnow()
    deadline = parse_deadline(jd.deadline)
    release_at, cutoff = release_time(now, deadline)
    if deadline is not None and deadline <= now:
        raise HTTPException(status_code=409, detail=f"The application deadline ({format_local(deadline)}) has passed.")
    if release_at - now < timedelta(minutes=settings.auto_apply_min_window_minutes):
        when = format_local(deadline) if deadline else "unknown"
        raise HTTPException(
            status_code=409,
            detail=(
                f"Too close to the application deadline ({when}): students would have less than "
                f"{settings.auto_apply_min_window_minutes:g} minutes to withdraw."
            ),
        )

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

        application = {
            "id": uuid.uuid4().hex,
            "student_id": student["id"],
            "jd_id": jd_id,
            "policy_id": policy_id,
            "score": breakdown.score,
            "match_json": breakdown.model_dump_json(),
            # The resume as scored: content-addressed file path (never overwritten) and text hash.
            "resume_path": student["resume_path"],
            "resume_sha": hashlib.sha256(student["resume_text"].encode("utf-8")).hexdigest(),
            "created_at": now,
            "release_at": release_at,
            "created_by": actor_id,
        }
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
