from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import CurrentUser, any_user, staff_only

from app.db import get_policy, list_policies, make_document_id, upsert_policy
from app.schemas import (
    PolicyDetail,
    PolicyIngestResponse,
    PolicyRules,
    PolicySummary,
)
from app.services.chunking import CLAUSE_CHUNK_OVERLAP, CLAUSE_CHUNK_SIZE
from app.services.grounding import ground_policy
from app.services.llm import extract_structured
from app.services.normalize import normalize_batch, normalize_branches, normalize_list
from app.services.pdf import resolve_source_text
from app.services.vectorstore import COLLECTION_POLICIES, ingest_document

router = APIRouter(prefix="/policies", tags=["policies"])

POLICY_INSTRUCTIONS = (
    "Extract campus placement policy rules. "
    "Capture minimum CGPA, maximum active backlogs, "
    "allowed branches (normalize to short uppercase codes: CSE, ECE, EEE, ME, CE, IT, AI-ML, DS, etc.; use [] when all branches are eligible), "
    "allowed batches only if the document explicitly names eligible graduating batches or years of "
    "graduation (normalize to 4-digit year strings like '2027'); an application deadline or posting "
    "date is not a batch, so otherwise use [], "
    "maximum applications per student, "
    "placed_students_can_apply (true if placed students are explicitly allowed, false if explicitly forbidden, null if not stated), "
    "and any rules that apply to already-placed students."
)


def _creator(user: CurrentUser) -> str | None:
    return None if user.id == "dev-admin" else user.id


@router.post("", response_model=PolicyIngestResponse)
async def create_policy(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    user: CurrentUser = Depends(staff_only),
) -> PolicyIngestResponse:
    source_text = await resolve_source_text(text, file)
    rules = extract_structured(source_text, PolicyRules, POLICY_INSTRUCTIONS)
    rules.allowed_branches = normalize_branches(rules.allowed_branches)
    rules.allowed_batches = normalize_list(rules.allowed_batches, normalize_batch)
    warnings = ground_policy(rules, source_text)
    policy_id = make_document_id(source_text)
    upsert_policy(policy_id, source_text, rules.model_dump_json(), created_by=_creator(user))
    ingest_document(
        COLLECTION_POLICIES,
        policy_id,
        "policy",
        source_text,
        chunk_size=CLAUSE_CHUNK_SIZE,
        chunk_overlap=CLAUSE_CHUNK_OVERLAP,
    )
    return PolicyIngestResponse(id=policy_id, rules=rules, warnings=warnings)


@router.get("", response_model=list[PolicySummary])
def list_policies_endpoint(_: CurrentUser = Depends(any_user)) -> list[PolicySummary]:
    rows = list_policies()
    return [
        PolicySummary(
            id=row["id"],
            min_cgpa=row.get("min_cgpa"),
            max_active_backlogs=row.get("max_active_backlogs"),
            allowed_branches=row.get("allowed_branches") or [],
            allowed_batches=row.get("allowed_batches") or [],
            placed_students_can_apply=row.get("placed_students_can_apply"),
        )
        for row in rows
    ]


@router.get("/{policy_id}", response_model=PolicyDetail)
def get_policy_endpoint(policy_id: str, _: CurrentUser = Depends(any_user)) -> PolicyDetail:
    row = get_policy(policy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return PolicyDetail(
        id=row["id"],
        rules=PolicyRules(**row["rules"]),
        source_text=row["source_text"],
    )
