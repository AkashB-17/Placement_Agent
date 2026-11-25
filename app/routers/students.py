from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import CurrentUser, require_role, staff_only
from app.config import get_settings
from app.db import (
    find_student_id,
    get_student,
    get_student_by_email,
    list_students,
    make_document_id,
    set_student_resume,
    update_student_record,
    upsert_student_record,
)
from app.schemas import (
    ParsedResume,
    ResumeLink,
    StudentDetail,
    StudentIngestResponse,
    StudentProfile,
    StudentSummary,
    StudentUpdate,
)
from app.services.llm import extract_structured
from app.services.normalize import normalize_batch, normalize_branch
from app.services.pdf import text_from_upload
from app.services.storage import resume_object_path, signed_resume_url, storage_enabled, upload_resume

router = APIRouter(prefix="/students", tags=["students"])

RESUME_INSTRUCTIONS = (
    "Extract the candidate resume into skills, projects, education, and experience. "
    "Use short strings for list items. Include only details present in the resume."
)


def _detail(row: dict) -> StudentDetail:
    profile = StudentProfile(
        name=row["name"],
        email=row["email"],
        branch=row["branch"],
        batch=row["batch"],
        cgpa=row["cgpa"],
        active_backlogs=row["active_backlogs"],
        is_placed=row["is_placed"],
    )
    return StudentDetail(
        id=row["id"],
        profile=profile,
        parsed_resume=ParsedResume(**row["parsed"]),
        resume_text=row["resume_text"],
        has_resume=bool(row["resume_text"].strip()),
        has_resume_file=bool(row["resume_path"]),
        resume_updated_at=row["resume_updated_at"],
    )


async def _prepare_cv(student_id: str, upload: UploadFile) -> tuple[str, ParsedResume, str | None]:
    """Read, parse and store a CV file; returns (text, parsed, storage path).

    Shared by the office (attaching a CV when adding a student) and the student (uploading
    or replacing their own). Runs before any database write, so a bad file or a storage
    failure saves nothing. The file goes to private storage under a content-addressed path,
    so earlier versions are never overwritten."""
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail="The CV file is empty.")
    resume_text = text_from_upload(upload.filename, data)
    if not resume_text:
        raise HTTPException(status_code=422, detail="Could not extract text from the CV file.")
    parsed = extract_structured(resume_text, ParsedResume, RESUME_INSTRUCTIONS)
    resume_path = None
    if storage_enabled():
        resume_path = resume_object_path(student_id, upload.filename, data)
        upload_resume(resume_path, data)
    return resume_text, parsed, resume_path


def _set_cv(student_id: str, cv: tuple[str, ParsedResume, str | None]) -> None:
    resume_text, parsed, resume_path = cv
    set_student_resume(student_id, resume_text, parsed.model_dump_json(), resume_path, datetime.now(UTC))


def owns_student_record(user: CurrentUser, student: dict) -> bool:
    """A student owns the record whose email matches their verified login email."""
    return bool(user.email and student.get("email") and user.email.lower() == student["email"].lower())


@router.post("", response_model=StudentIngestResponse)
async def create_student(
    name: str = Form(...),
    branch: str = Form(...),
    batch: str = Form(...),
    cgpa: float = Form(..., ge=0, le=10),
    active_backlogs: int = Form(..., ge=0),
    is_placed: bool = Form(False),
    email: str | None = Form(None, description="Student's login email; links the record to their account"),
    resume: UploadFile | None = File(None, description="Optional: students can upload their own CV"),
    user: CurrentUser = Depends(staff_only),
) -> StudentIngestResponse:
    """Add or update a student's academic record. Academic fields come from the placement
    office, so only staff create records; the CV is optional because students upload it."""
    branch = normalize_branch(branch)
    batch = normalize_batch(batch)
    if not branch or not batch or not name.strip():
        raise HTTPException(status_code=422, detail="Name, branch and batch must not be blank.")
    email = (email or "").strip().lower() or None
    if email is not None and "@" not in email:
        raise HTTPException(status_code=422, detail="Email is not valid.")
    has_cv = resume is not None and bool(resume.filename)
    if not has_cv and email is None:
        raise HTTPException(
            status_code=422,
            detail="Add the student's login email so they can upload their CV, or attach a CV now.",
        )

    # Stable id: re-adding the same student updates their record (and keeps their CV),
    # instead of creating a duplicate. A new CV never changes the id.
    student_id = find_student_id(email, name.strip(), branch, batch) or (
        make_document_id("student", email) if email else make_document_id(name.strip(), branch, batch)
    )
    cv = await _prepare_cv(student_id, resume) if has_cv else None
    upsert_student_record(
        student_id,
        name=name.strip(),
        branch=branch,
        batch=batch,
        cgpa=cgpa,
        active_backlogs=active_backlogs,
        is_placed=is_placed,
        email=email,
        created_by=user.id if user.id != "dev-admin" else None,
    )
    if cv is not None:
        _set_cv(student_id, cv)
    # CVs are not embedded: scoring reads the full text, and keeping CV chunks in the local
    # vector store would leave student data on this machine.
    row = get_student(student_id)
    parsed = ParsedResume(**row["parsed"])
    profile = StudentProfile(
        name=row["name"],
        email=row["email"],
        branch=row["branch"],
        batch=row["batch"],
        cgpa=row["cgpa"],
        active_backlogs=row["active_backlogs"],
        is_placed=row["is_placed"],
        parsed_resume=parsed,
    )
    return StudentIngestResponse(id=student_id, profile=profile, parsed_resume=parsed)


@router.put("/me/resume", response_model=StudentDetail)
async def upload_my_resume(
    resume: UploadFile = File(..., description="Your CV as a .pdf or .txt file"),
    user: CurrentUser = Depends(require_role("student")),
) -> StudentDetail:
    """A student uploads or replaces their own CV. Academic details stay as the office set them."""
    row = get_student_by_email(user.email) if user.email else None
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No student record is linked to your email yet. Ask the placement office to add you first.",
        )
    _set_cv(row["id"], await _prepare_cv(row["id"], resume))
    return _detail(get_student(row["id"]))


@router.get("", response_model=list[StudentSummary])
def list_students_endpoint(_: CurrentUser = Depends(staff_only)) -> list[StudentSummary]:
    return [
        StudentSummary(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            branch=row["branch"],
            batch=row["batch"],
            cgpa=row["cgpa"],
            active_backlogs=row["active_backlogs"],
            is_placed=row["is_placed"],
        )
        for row in list_students()
    ]


@router.get("/me", response_model=StudentDetail)
def get_my_record(user: CurrentUser = Depends(require_role("student"))) -> StudentDetail:
    row = get_student_by_email(user.email) if user.email else None
    if row is None:
        raise HTTPException(status_code=404, detail="No student record is linked to your email yet.")
    return _detail(row)


@router.get("/{student_id}", response_model=StudentDetail)
def get_student_endpoint(student_id: str, _: CurrentUser = Depends(staff_only)) -> StudentDetail:
    row = get_student(student_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Student not found.")
    return _detail(row)


@router.put("/{student_id}", response_model=StudentDetail)
def update_student_endpoint(
    student_id: str, body: StudentUpdate, _: CurrentUser = Depends(staff_only)
) -> StudentDetail:
    """The placement office corrects a student's academic record: name, email, branch,
    batch, CGPA, backlogs, placed. The id and the student's CV never change. Eligibility
    is recomputed from the record on every check, so the new values apply at once;
    applications already made keep the snapshot taken when they were made."""
    row = get_student(student_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Student not found.")
    branch = normalize_branch(body.branch)
    batch = normalize_batch(body.batch)
    name = body.name.strip()
    if not branch or not batch or not name:
        raise HTTPException(status_code=422, detail="Name, branch and batch must not be blank.")
    email = (body.email or "").strip().lower() or None
    if email is not None and "@" not in email:
        raise HTTPException(status_code=422, detail="Email is not valid.")
    if email is None and not (row["resume_text"] or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Keep a login email: without one and without a CV, the student can never upload a CV.",
        )
    if email is not None:
        # The email is how a login finds its record, so two records can't share one.
        other = get_student_by_email(email)
        if other is not None and other["id"] != student_id:
            raise HTTPException(status_code=409, detail=f"Another student ({other['name']}) already uses {email}.")
    update_student_record(
        student_id,
        name=name,
        email=email,
        branch=branch,
        batch=batch,
        cgpa=body.cgpa,
        active_backlogs=body.active_backlogs,
        is_placed=body.is_placed,
    )
    return _detail(get_student(student_id))


@router.get("/{student_id}/resume", response_model=ResumeLink)
def get_resume_link(
    student_id: str,
    user: CurrentUser = Depends(require_role("officer", "admin", "student")),
) -> ResumeLink:
    row = get_student(student_id)
    if row is None or (user.role == "student" and not owns_student_record(user, row)):
        # Same 404 for "missing" and "not yours", so ids can't be probed.
        raise HTTPException(status_code=404, detail="Student not found.")
    if not row["resume_path"]:
        raise HTTPException(status_code=404, detail="No resume file stored for this student.")
    return ResumeLink(url=signed_resume_url(row["resume_path"]), expires_in=get_settings().signed_url_ttl_seconds)
