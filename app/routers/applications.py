"""
Staged auto-apply endpoints.

Students opt in and manage their own applications ("me" = the student record linked to
their verified login email). Officers/admins run auto-apply for a JD and see everything.
Recruiters see an application only after it is released, and only for JDs they created.
Every list/read first runs the release sweep, so statuses are never stale.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app import db
from app.auth import CurrentUser, require_role, staff_only
from app.config import get_settings
from app.schemas import (
    ApplicationOut,
    CvTipsResponse,
    JDRequirements,
    MyJob,
    MyJobApplication,
    MyJobsResponse,
    PolicyRules,
    ApplicationStatus,
    AutoApplyPreferences,
    AutoApplyRun,
    AutoApplyRunRecord,
    NotificationOut,
    PreferencesOut,
    ResumeLink,
)
from app.services import auto_apply
from app.services.app_settings import auto_apply_threshold
from app.services.cv_tips import cv_tips
from app.services.eligibility import check_eligibility
from app.services.matching import evaluate_student, load_jd, load_policy
from app.services.storage import signed_resume_url

router = APIRouter(tags=["auto-apply"])
student_only = require_role("student")
MAX_COMPANY_NAME = 100


def _my_student(user: CurrentUser) -> dict:
    row = db.get_student_by_email(user.email) if user.email else None
    if row is None:
        raise HTTPException(status_code=404, detail="No student record is linked to your email yet.")
    return row


# ── Student: preferences ────────────────────────────────────────────────────

def _preferences_out(prefs: dict | None) -> PreferencesOut:
    settings = get_settings()
    threshold = auto_apply_threshold()
    return PreferencesOut(
        enabled=bool(prefs and prefs["enabled"]),
        min_score=prefs["min_score"] if prefs else threshold,
        excluded_companies=prefs["excluded_companies"] if prefs else [],
        threshold=threshold,
        withdraw_hours=settings.auto_apply_withdraw_hours,
    )


@router.get("/me/auto-apply", response_model=PreferencesOut)
def get_my_preferences(user: CurrentUser = Depends(student_only)) -> PreferencesOut:
    return _preferences_out(db.get_preferences(_my_student(user)["id"]))


@router.put("/me/auto-apply", response_model=PreferencesOut)
def set_my_preferences(body: AutoApplyPreferences, user: CurrentUser = Depends(student_only)) -> PreferencesOut:
    threshold = auto_apply_threshold()
    if body.min_score < threshold:
        raise HTTPException(
            status_code=422,
            detail=f"Minimum score can't be below the college threshold of {threshold:g}.",
        )
    companies: list[str] = []
    for name in body.excluded_companies:
        name = " ".join(name.split())[:MAX_COMPANY_NAME]
        if name and name.casefold() not in {c.casefold() for c in companies}:
            companies.append(name)
    student_id = _my_student(user)["id"]
    db.upsert_preferences(student_id, body.enabled, body.min_score, companies, auto_apply.utcnow())
    return _preferences_out(db.get_preferences(student_id))


# ── Student: applications and notifications ─────────────────────────────────

@router.get("/me/applications", response_model=list[ApplicationOut])
def my_applications(user: CurrentUser = Depends(student_only)) -> list[ApplicationOut]:
    auto_apply.release_due()
    student_id = _my_student(user)["id"]
    now = auto_apply.utcnow()
    return [auto_apply.to_out(a, now) for a in db.list_applications(student_id=student_id)]


@router.post("/applications/{application_id}/withdraw", response_model=ApplicationOut)
def withdraw(application_id: str, user: CurrentUser = Depends(student_only)) -> ApplicationOut:
    student = _my_student(user)
    auto_apply.release_due()
    application = db.get_application(application_id)
    if application is None or application["student_id"] != student["id"]:
        raise HTTPException(status_code=404, detail="Application not found.")

    label = " – ".join(p for p in (application["company"], application["role"]) if p) or "this job"
    if not db.withdraw_application(
        application_id, student["id"], auto_apply.utcnow(), f"You withdrew your application to {label}."
    ):
        current = db.get_application(application_id) or application
        if current["status"] == "submitted":
            raise HTTPException(status_code=409, detail="Too late: this application has already been sent to the company.")
        raise HTTPException(status_code=409, detail=f"This application is already {current['status']}.")
    return auto_apply.to_out(db.get_application(application_id))


@router.get("/me/jobs", response_model=MyJobsResponse)
def my_jobs(
    policy_id: str | None = Query(None, description="Policy to check eligibility against; default: the newest"),
    user: CurrentUser = Depends(student_only),
) -> MyJobsResponse:
    """The student's job board in one request: every JD with its deadline, the student's
    eligibility (deterministic rules, with reasons) and their application, if any.
    No LLM or embedding calls: scores are fetched per job on demand via POST /match."""
    student = _my_student(user)
    auto_apply.release_due()

    if policy_id is not None:
        row = db.get_policy(policy_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Policy not found.")
        rules = PolicyRules(**row["rules"])
    else:
        policy_id = _newest_policy_id()
        rules = PolicyRules(**db.get_policy(policy_id)["rules"]) if policy_id else PolicyRules()

    now = auto_apply.utcnow()
    applications = {a["jd_id"]: a for a in db.list_applications(student_id=student["id"])}
    jobs: list[MyJob] = []
    for row in db.list_jd_rows():
        jd = JDRequirements(**row["requirements"])
        deadline_at = auto_apply.parse_deadline(jd.deadline)
        app = applications.get(row["id"])
        jobs.append(
            MyJob(
                id=row["id"],
                company=jd.company,
                role=jd.role,
                ctc=jd.ctc,
                deadline=jd.deadline,
                deadline_at=deadline_at,
                posted_at=row["created_at"],
                closed=deadline_at is not None and deadline_at <= now,
                deadline_changed_at=row["deadline_changed_at"],
                eligibility=check_eligibility(student, rules, jd),
                application=MyJobApplication(
                    id=app["id"],
                    status=app["status"],
                    release_at=app["release_at"],
                    can_withdraw=app["status"] == "pending" and app["release_at"] > now,
                    source=app["source"],
                ) if app else None,
            )
        )
    return MyJobsResponse(policy_id=policy_id, jobs=jobs)


def _newest_policy_id() -> str | None:
    policies = db.list_policies()
    return policies[0]["id"] if policies else None


def _policy_or_newest(policy_id: str | None) -> str:
    """The policy a student's request is judged against: the one given, else the newest."""
    policy_id = policy_id or _newest_policy_id()
    if policy_id is None:
        raise HTTPException(status_code=409, detail="The placement office hasn't published a policy yet.")
    return policy_id


@router.post("/me/jobs/{jd_id}/apply", response_model=ApplicationOut, status_code=201)
def apply_to_job(
    jd_id: str,
    policy_id: str | None = Query(None, description="Policy to check eligibility against; default: the newest"),
    user: CurrentUser = Depends(student_only),
) -> ApplicationOut:
    """The student applies themselves. Same staged pipeline as auto-apply: eligibility by
    code, score snapshot, pinned CV, then a withdraw window before it is sent."""
    student = _my_student(user)
    return auto_apply.apply_manually(student, jd_id, _policy_or_newest(policy_id), actor_id=user.id)


@router.post("/me/jobs/{jd_id}/cv-tips", response_model=CvTipsResponse)
def my_cv_tips(
    jd_id: str,
    policy_id: str | None = Query(None, description="Policy to check eligibility against; default: the newest"),
    user: CurrentUser = Depends(student_only),
) -> CvTipsResponse:
    """What this job asks for that the student's CV doesn't show, with a suggestion per gap.
    The gaps come from the verified score breakdown; the AI only writes the advice."""
    student = _my_student(user)
    policy_id = _policy_or_newest(policy_id)
    jd = load_jd(jd_id)
    if not (student.get("resume_text") or "").strip():
        raise HTTPException(status_code=409, detail="Upload your CV under Profile & CV first.")
    policy = load_policy(policy_id)
    if not check_eligibility(student, policy, jd).eligible:  # rules first: no AI call if ineligible
        raise HTTPException(
            status_code=409,
            detail="CV tips are for jobs you're eligible for: the rules you miss can't be fixed by editing a CV.",
        )
    result = evaluate_student(student, policy, jd, policy_id, jd_id)
    if result.score_breakdown is None:
        raise HTTPException(
            status_code=409,
            detail="CV tips are for jobs you're eligible for: the rules you miss can't be fixed by editing a CV.",
        )
    tips, source = cv_tips(student, jd, jd_id, result.score_breakdown)
    return CvTipsResponse(jd_id=jd_id, score=result.score_breakdown.score, tips=tips, source=source)


@router.get("/me/notifications", response_model=list[NotificationOut])
def my_notifications(user: CurrentUser = Depends(student_only)) -> list[NotificationOut]:
    auto_apply.release_due()
    return [NotificationOut(**n) for n in db.list_notifications(_my_student(user)["id"])]


@router.post("/me/notifications/read", status_code=204)
def mark_read(user: CurrentUser = Depends(student_only)) -> None:
    db.mark_notifications_read(_my_student(user)["id"], auto_apply.utcnow())


# ── Officer: run auto-apply ─────────────────────────────────────────────────

@router.post("/jds/{jd_id}/auto-apply", response_model=AutoApplyRun)
def run_auto_apply(
    jd_id: str,
    policy_id: str = Query(..., description="Policy to check eligibility against"),
    user: CurrentUser = Depends(staff_only),
) -> AutoApplyRun:
    return auto_apply.run_auto_apply(jd_id, policy_id, actor_id=user.id if user.id != "dev-admin" else None)


@router.get("/auto-apply/runs", response_model=list[AutoApplyRunRecord])
def auto_apply_runs(
    jd_id: str | None = Query(None, description="Only runs for this JD"),
    limit: int = Query(20, ge=1, le=500),
    _: CurrentUser = Depends(staff_only),
) -> list[AutoApplyRunRecord]:
    """Recorded auto-apply runs, newest first: automatic ones after each JD upload and the
    ones staff ran, with who was applied and why each other student was skipped."""
    return [AutoApplyRunRecord(**run) for run in db.list_auto_apply_runs(jd_id=jd_id, limit=limit)]


# ── Staff and recruiters: list ──────────────────────────────────────────────

@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    jd_id: str | None = None,
    status: ApplicationStatus | None = None,
    user: CurrentUser = Depends(require_role("officer", "admin", "recruiter")),
) -> list[ApplicationOut]:
    auto_apply.release_due()
    if user.role == "recruiter":
        # Recruiters never see pending or withdrawn applications: those are not sent.
        if status not in (None, "submitted"):
            return []
        rows = db.list_applications(jd_id=jd_id, status="submitted", jd_created_by=user.id)
    else:
        rows = db.list_applications(jd_id=jd_id, status=status)
    now = auto_apply.utcnow()
    return [auto_apply.to_out(a, now) for a in rows]


@router.get("/applications/{application_id}/resume", response_model=ResumeLink)
def application_resume(
    application_id: str,
    user: CurrentUser = Depends(require_role("officer", "admin", "recruiter", "student")),
) -> ResumeLink:
    """The resume version pinned when the application was created, not the latest upload."""
    auto_apply.release_due()
    application = db.get_application(application_id)
    allowed = application is not None and (
        user.role in ("officer", "admin")
        or (user.role == "student" and application["student_id"] == _my_student(user)["id"])
        or (
            user.role == "recruiter"
            and application["status"] == "submitted"
            and application["jd_created_by"] == user.id
        )
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="Application not found.")
    if not application["resume_path"]:
        raise HTTPException(status_code=404, detail="No resume file is stored for this application.")
    return ResumeLink(
        url=signed_resume_url(application["resume_path"]), expires_in=get_settings().signed_url_ttl_seconds
    )
