from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.db import make_document_id, upsert_student
from app.schemas import ParsedResume, StudentIngestResponse, StudentProfile
from app.services.llm import extract_structured
from app.services.pdf import extract_pdf_text
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
    cgpa: float = Form(...),
    active_backlogs: int = Form(...),
    resume: UploadFile = File(...),
) -> StudentIngestResponse:
    data = await resume.read()
    if not data:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    resume_text = extract_pdf_text(data)
    if not resume_text:
        raise HTTPException(status_code=422, detail="Could not extract text from the resume PDF.")

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
        parsed_resume=parsed,
    )
    return StudentIngestResponse(id=student_id, profile=profile, parsed_resume=parsed)
