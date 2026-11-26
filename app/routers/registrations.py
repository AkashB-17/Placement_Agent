"""
Self sign-up: a student asks to be added; staff approve instead of typing them in.

A signed-in student whose verified email isn't on any student record submits their
academic details (self-reported). Staff (officer/admin) review the request, correct any
value, and approve it, which creates the student record with that email, so the account is
linked from then on. Or they reject it with a note, and the student can fix and resubmit.
The office still owns the record: a student can never edit it after approval.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app import db
from app.auth import CurrentUser, require_role, staff_only
from app.schemas import ApproveRegistration, MyRegistration, RegistrationIn, RegistrationOut, RejectRegistration
from app.services.normalize import normalize_batch, normalize_branch

router = APIRouter(tags=["registrations"])
student_only = require_role("student")


def _clean(body: RegistrationIn) -> dict:
    name = " ".join(body.name.split())
    branch = normalize_branch(body.branch)
    batch = normalize_batch(body.batch)
    if not name or not branch or not batch:
        raise HTTPException(status_code=422, detail="Name, branch and batch must not be blank.")
    return {"name": name, "branch": branch, "batch": batch, "cgpa": body.cgpa, "active_backlogs": body.active_backlogs}


def _actor(user: CurrentUser) -> str | None:
    return None if user.id == "dev-admin" else user.id


# ── Student ─────────────────────────────────────────────────────────────────

@router.get("/me/registration", response_model=MyRegistration)
def my_registration(user: CurrentUser = Depends(student_only)) -> MyRegistration:
    linked = bool(user.email) and db.get_student_by_email(user.email) is not None
    request = db.get_registration_request(user.id)
    return MyRegistration(linked=linked, request=RegistrationOut(**request) if request else None)


@router.post("/me/registration", response_model=MyRegistration)
def submit_registration(body: RegistrationIn, user: CurrentUser = Depends(student_only)) -> MyRegistration:
    """Ask the placement office to add you. Resubmitting (e.g. after a rejection) replaces
    the previous request and puts it back in the queue."""
    if not user.email:
        raise HTTPException(status_code=400, detail="Your account has no email address.")
    if db.get_student_by_email(user.email) is not None:
        raise HTTPException(status_code=409, detail="Your account is already linked to a student record.")
    existing = db.get_registration_request(user.id)
    if existing and existing["status"] == "approved":
        raise HTTPException(status_code=409, detail="Your registration was already approved.")
    db.submit_registration_request({"user_id": user.id, "email": user.email.lower(), **_clean(body)}, datetime.now(UTC))
    return my_registration(user)


# ── Staff ───────────────────────────────────────────────────────────────────

@router.get("/registrations", response_model=list[RegistrationOut])
def list_registrations(
    status: str | None = Query("pending", pattern="^(pending|approved|rejected)$"),
    _: CurrentUser = Depends(staff_only),
) -> list[RegistrationOut]:
    return [RegistrationOut(**r) for r in db.list_registration_requests(status)]


def _pending(user_id: str) -> dict:
    request = db.get_registration_request(user_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Registration request not found.")
    if request["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"This request was already {request['status']}.")
    return request


@router.post("/registrations/{user_id}/approve", response_model=RegistrationOut)
def approve_registration(
    user_id: str, body: ApproveRegistration | None = None, user: CurrentUser = Depends(staff_only)
) -> RegistrationOut:
    """Create the student record from the request (with any corrections) and link the account.
    If a record with this email already exists (the office added them meanwhile), it is
    kept as it is and the request is simply marked approved."""
    request = _pending(user_id)
    email = request["email"]
    if db.get_student_by_email(email) is None:
        values = _clean(body) if body else {k: request[k] for k in ("name", "branch", "batch", "cgpa", "active_backlogs")}
        student_id = db.find_student_id(email, values["name"], values["branch"], values["batch"]) or db.make_document_id(
            "student", email
        )
        db.upsert_student_record(student_id, email=email, is_placed=False, created_by=_actor(user), **values)
    if not db.decide_registration_request(user_id, "approved", datetime.now(UTC), _actor(user), None):
        raise HTTPException(status_code=409, detail="This request was decided by someone else just now.")
    return RegistrationOut(**db.get_registration_request(user_id))


@router.post("/registrations/{user_id}/reject", response_model=RegistrationOut)
def reject_registration(
    user_id: str, body: RejectRegistration, user: CurrentUser = Depends(staff_only)
) -> RegistrationOut:
    """Turn a request down with a reason the student sees; they can fix it and resubmit."""
    _pending(user_id)
    if not db.decide_registration_request(user_id, "rejected", datetime.now(UTC), _actor(user), " ".join(body.note.split())):
        raise HTTPException(status_code=409, detail="This request was decided by someone else just now.")
    return RegistrationOut(**db.get_registration_request(user_id))
