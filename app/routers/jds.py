from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import CurrentUser, any_user, require_role

from app.db import get_jd, list_jds, make_document_id, upsert_jd
from app.schemas import JDDetail, JDIngestResponse, JDRequirements, JDSummary
from app.services.chunking import CLAUSE_CHUNK_OVERLAP, CLAUSE_CHUNK_SIZE
from app.services.grounding import ground_jd
from app.services.llm import extract_structured
from app.services.normalize import normalize_batch, normalize_branch, normalize_list
from app.services.pdf import resolve_source_text
from app.services.vectorstore import COLLECTION_JDS, ingest_document

router = APIRouter(prefix="/jds", tags=["jds"])

JD_INSTRUCTIONS = (
    "Extract job description requirements. "
    "Capture company, role, required skills, preferred skills, any CGPA override, "
    "allowed branches (normalize to short uppercase codes: CSE, ECE, EEE, ME, CE, IT, AI-ML, DS, etc.), "
    "allowed batches only if the document explicitly names eligible graduating batches or years of "
    "graduation (normalize to 4-digit year strings like '2027'); an application deadline or posting "
    "date is not a batch, so otherwise use [], "
    "CTC, deadline, and experience required."
)


@router.post("", response_model=JDIngestResponse)
async def create_jd(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    user: CurrentUser = Depends(require_role("officer", "admin", "recruiter")),
) -> JDIngestResponse:
    source_text = await resolve_source_text(text, file)
    requirements = extract_structured(source_text, JDRequirements, JD_INSTRUCTIONS)
    requirements.allowed_branches = normalize_list(requirements.allowed_branches, normalize_branch)
    requirements.allowed_batches = normalize_list(requirements.allowed_batches, normalize_batch)
    warnings = ground_jd(requirements, source_text)
    jd_id = make_document_id(source_text)
    existing = get_jd(jd_id)
    if user.role == "recruiter" and existing and existing["created_by"] not in (None, user.id):
        raise HTTPException(status_code=403, detail="This JD belongs to another user.")
    created_by = None if user.id == "dev-admin" else user.id
    upsert_jd(jd_id, source_text, requirements.model_dump_json(), created_by=created_by)
    ingest_document(
        COLLECTION_JDS,
        jd_id,
        "jd",
        source_text,
        chunk_size=CLAUSE_CHUNK_SIZE,
        chunk_overlap=CLAUSE_CHUNK_OVERLAP,
    )
    return JDIngestResponse(id=jd_id, requirements=requirements, warnings=warnings)


@router.get("", response_model=list[JDSummary])
def list_jds_endpoint(_: CurrentUser = Depends(any_user)) -> list[JDSummary]:
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
def get_jd_endpoint(jd_id: str, _: CurrentUser = Depends(any_user)) -> JDDetail:
    row = get_jd(jd_id)
    if row is None:
        raise HTTPException(status_code=404, detail="JD not found.")
    return JDDetail(
        id=row["id"],
        requirements=JDRequirements(**row["requirements"]),
        source_text=row["source_text"],
    )
