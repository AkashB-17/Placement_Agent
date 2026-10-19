from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.db import get_jd, list_jds, make_document_id, upsert_jd
from app.schemas import JDDetail, JDIngestResponse, JDRequirements, JDSummary
from app.services.llm import extract_structured
from app.services.normalize import normalize_batch, normalize_branch, normalize_list
from app.services.pdf import resolve_source_text
from app.services.vectorstore import COLLECTION_JDS, ingest_document

router = APIRouter(prefix="/jds", tags=["jds"])

JD_INSTRUCTIONS = (
    "Extract job description requirements. "
    "Capture company, role, required skills, preferred skills, any CGPA override, "
    "allowed branches (normalize to short uppercase codes: CSE, ECE, EEE, ME, CE, IT, AI-ML, DS, etc.), "
    "allowed batches (normalize to 4-digit graduation year strings like '2027'), "
    "CTC, deadline, and experience required."
)


@router.post("", response_model=JDIngestResponse)
async def create_jd(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> JDIngestResponse:
    source_text = await resolve_source_text(text, file)
    requirements = extract_structured(source_text, JDRequirements, JD_INSTRUCTIONS)
    requirements.allowed_branches = normalize_list(requirements.allowed_branches, normalize_branch)
    requirements.allowed_batches = normalize_list(requirements.allowed_batches, normalize_batch)
    jd_id = make_document_id(source_text)
    upsert_jd(jd_id, source_text, requirements.model_dump_json())
    ingest_document(COLLECTION_JDS, jd_id, "jd", source_text)
    return JDIngestResponse(id=jd_id, requirements=requirements)


@router.get("", response_model=list[JDSummary])
def list_jds_endpoint() -> list[JDSummary]:
    rows = list_jds()
    return [
        JDSummary(
            id=row["id"],
            company=row.get("company"),
            role=row.get("role"),
            required_skills=row.get("required_skills") or [],
            allowed_branches=row.get("allowed_branches") or [],
        )
        for row in rows
    ]


@router.get("/{jd_id}", response_model=JDDetail)
def get_jd_endpoint(jd_id: str) -> JDDetail:
    row = get_jd(jd_id)
    if row is None:
        raise HTTPException(status_code=404, detail="JD not found.")
    return JDDetail(
        id=row["id"],
        requirements=JDRequirements(**row["requirements"]),
        source_text=row["source_text"],
    )
