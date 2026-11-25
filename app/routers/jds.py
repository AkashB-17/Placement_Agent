from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import CurrentUser, any_user, require_role

from app.db import get_jd, list_jds, make_document_id, upsert_jd
from app.schemas import DeadlineChange, DeadlineUpdate, JDDetail, JDIngestResponse, JDRequirements, JDSummary
from app.services import auto_apply
from app.services.chunking import CLAUSE_CHUNK_OVERLAP, CLAUSE_CHUNK_SIZE
from app.services.grounding import ground_jd
from app.services.llm import extract_structured
from app.services.normalize import normalize_batch, normalize_branches, normalize_list
from app.services.pdf import resolve_source_text
from app.services.vectorstore import COLLECTION_JDS, ingest_document

router = APIRouter(prefix="/jds", tags=["jds"])

JD_INSTRUCTIONS = (
    "Extract job description requirements. "
    "Capture company, role, required skills, preferred skills, any CGPA override, "
    "allowed branches (normalize to short uppercase codes: CSE, ECE, EEE, ME, CE, IT, AI-ML, DS, etc.; use [] when all branches are eligible), "
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
    requirements.allowed_branches = normalize_branches(requirements.allowed_branches)
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


def can_edit_deadline(user: CurrentUser, created_by: str | None) -> bool:
    """Officers and admins may change any job's deadline; a recruiter only their own jobs'."""
    return user.role in ("officer", "admin") or (user.role == "recruiter" and created_by == user.id)


@router.get("", response_model=list[JDSummary])
def list_jds_endpoint(user: CurrentUser = Depends(any_user)) -> list[JDSummary]:
    rows = list_jds()
    return [
        JDSummary(
            id=row["id"],
            company=row.get("company"),
            role=row.get("role"),
            required_skills=row.get("required_skills") or [],
            allowed_branches=row.get("allowed_branches") or [],
            deadline=row.get("deadline"),
            deadline_at=auto_apply.parse_deadline(row.get("deadline")),
            original_deadline=row["original_deadline"],
            deadline_changed_at=row["deadline_changed_at"],
            can_edit_deadline=can_edit_deadline(user, row["created_by"]),
        )
        for row in rows
    ]


@router.put("/{jd_id}/deadline", response_model=DeadlineChange)
def change_deadline(
    jd_id: str,
    body: DeadlineUpdate,
    user: CurrentUser = Depends(require_role("officer", "admin", "recruiter")),
) -> DeadlineChange:
    """Extend or shorten a job's deadline. Shortening moves pending applications earlier
    (never past the new deadline) and notifies those students."""
    row = get_jd(jd_id)
    if row is None or (user.role == "recruiter" and not can_edit_deadline(user, row["created_by"])):
        # A recruiter can't tell another recruiter's job from a missing one.
        raise HTTPException(status_code=404, detail="JD not found.")
    actor = None if user.id == "dev-admin" else user.id
    return auto_apply.change_deadline(jd_id, body.deadline, actor)


@router.get("/{jd_id}", response_model=JDDetail)
def get_jd_endpoint(jd_id: str, _: CurrentUser = Depends(any_user)) -> JDDetail:
    row = get_jd(jd_id)
    if row is None:
        raise HTTPException(status_code=404, detail="JD not found.")
    return JDDetail(
        id=row["id"],
        requirements=JDRequirements(**row["requirements"]),
        source_text=row["source_text"],
        original_deadline=row["original_deadline"],
        deadline_changed_at=row["deadline_changed_at"],
    )
