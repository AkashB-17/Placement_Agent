from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import CurrentUser, require_role, staff_only
from app.config import get_settings
from app.db import get_student, get_student_by_email, list_students, make_document_id, upsert_student
from app.schemas import (
    ParsedResume,
    ResumeLink,
    StudentDetail,
    StudentIngestResponse,
    StudentProfile,
    StudentSummary,
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
        has_resume_file=bool(row["resume_path"]),
    )


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
    resume: UploadFile = File(...),
    user: CurrentUser = Depends(staff_only),
) -> StudentIngestResponse:
    # Academic fields come from the placement office, so only staff create records.
    branch = normalize_branch(branch)
    batch = normalize_batch(batch)
    if not branch or not batch:
        raise HTTPException(status_code=422, detail="Branch and batch must not be blank.")
    email = (email or "").strip().lower() or None
    if email is not None and "@" not in email:
        raise HTTPException(status_code=422, detail="Email is not valid.")

    data = await resume.read()
    if not data:
        raise HTTPException(status_code=400, detail="Resume file is empty.")

    resume_text = text_from_upload(resume.filename, data)
    if not resume_text:
        raise HTTPException(status_code=422, detail="Could not extract text from the resume file.")

    parsed = extract_structured(resume_text, ParsedResume, RESUME_INSTRUCTIONS)
    student_id = make_document_id(name, branch, batch, resume_text)

    resume_path = None
    if storage_enabled():
        resume_path = resume_object_path(student_id, resume.filename, data)
        upload_resume(resume_path, data)

    upsert_student(
        student_id,
        name=name,
        branch=branch,
        batch=batch,
        cgpa=cgpa,
        active_backlogs=active_backlogs,
        resume_text=resume_text,
        parsed_json=parsed.model_dump_json(),
        is_placed=is_placed,
        email=email,
        resume_path=resume_path,
        created_by=user.id if user.id != "dev-admin" else None,
    )
    # Resumes are not embedded: scoring reads the full text, and keeping resume chunks
    # in the local vector store would leave student data on this machine.
    profile = StudentProfile(
        name=name,
        email=email,
        branch=branch,
        batch=batch,
        cgpa=cgpa,
        active_backlogs=active_backlogs,
        is_placed=is_placed,
        parsed_resume=parsed,
    )
    return StudentIngestResponse(id=student_id, profile=profile, parsed_resume=parsed)


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
