from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.db import get_student, list_students, make_document_id, upsert_student
from app.schemas import (
    ParsedResume,
    StudentDetail,
    StudentIngestResponse,
    StudentProfile,
    StudentSummary,
)
from app.services.llm import extract_structured
from app.services.normalize import normalize_batch, normalize_branch
from app.services.pdf import text_from_upload
from app.services.vectorstore import COLLECTION_RESUMES, ingest_document

router = APIRouter(prefix="/students", tags=["students"])

RESUME_INSTRUCTIONS = (
    "Extract the candidate resume into skills, projects, education, and experience. "
    "Use short strings for list items. Include only details present in the resume."
)


@router.post("", response_model=StudentIngestResponse)
async def create_student(
    name: str = Form(...),
    branch: str = Form(...),
    batch: str = Form(...),
    cgpa: float = Form(..., ge=0, le=10),
    active_backlogs: int = Form(..., ge=0),
    is_placed: bool = Form(False),
    resume: UploadFile = File(...),
) -> StudentIngestResponse:
    branch = normalize_branch(branch)
    batch = normalize_batch(batch)
    if not branch or not batch:
        raise HTTPException(status_code=422, detail="Branch and batch must not be blank.")

    data = await resume.read()
    if not data:
        raise HTTPException(status_code=400, detail="Resume file is empty.")

    resume_text = text_from_upload(resume.filename, data)
    if not resume_text:
        raise HTTPException(status_code=422, detail="Could not extract text from the resume file.")

    parsed = extract_structured(resume_text, ParsedResume, RESUME_INSTRUCTIONS)
    student_id = make_document_id(name, branch, batch, resume_text)
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
    )
    ingest_document(
        COLLECTION_RESUMES,
        student_id,
        "resume",
        resume_text,
        extra_metadata={"student_id": student_id},
    )
    profile = StudentProfile(
        name=name,
        branch=branch,
        batch=batch,
        cgpa=cgpa,
        active_backlogs=active_backlogs,
        is_placed=is_placed,
        parsed_resume=parsed,
    )
    return StudentIngestResponse(id=student_id, profile=profile, parsed_resume=parsed)


@router.get("", response_model=list[StudentSummary])
def list_students_endpoint() -> list[StudentSummary]:
    rows = list_students()
    return [
        StudentSummary(
            id=row["id"],
            name=row["name"],
            branch=row["branch"],
            batch=row["batch"],
            cgpa=row["cgpa"],
            active_backlogs=row["active_backlogs"],
            is_placed=bool(row["is_placed"]),
        )
        for row in rows
    ]


@router.get("/{student_id}", response_model=StudentDetail)
def get_student_endpoint(student_id: str) -> StudentDetail:
    row = get_student(student_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Student not found.")
    profile = StudentProfile(
        name=row["name"],
        branch=row["branch"],
        batch=row["batch"],
        cgpa=row["cgpa"],
        active_backlogs=row["active_backlogs"],
        is_placed=row["is_placed"],
    )
    parsed = ParsedResume(**row["parsed"])
    return StudentDetail(
        id=row["id"],
        profile=profile,
        parsed_resume=parsed,
        resume_text=row["resume_text"],
    )
