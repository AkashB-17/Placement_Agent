from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.db import get_policy, list_policies, make_document_id, upsert_policy
from app.schemas import (
    PolicyDetail,
    PolicyIngestResponse,
    PolicyRules,
    PolicySummary,
)
from app.services.llm import extract_structured
from app.services.normalize import normalize_batch, normalize_branch, normalize_list
from app.services.pdf import resolve_source_text
from app.services.vectorstore import COLLECTION_POLICIES, ingest_document

router = APIRouter(prefix="/policies", tags=["policies"])

POLICY_INSTRUCTIONS = (
    "Extract campus placement policy rules. "
    "Capture minimum CGPA, maximum active backlogs, "
    "allowed branches (normalize to short uppercase codes: CSE, ECE, EEE, ME, CE, IT, AI-ML, DS, etc.), "
    "allowed batches (normalize to 4-digit graduation year strings like '2027'), "
    "maximum applications per student, "
    "placed_students_can_apply (true if placed students are explicitly allowed, false if explicitly forbidden, null if not stated), "
    "and any rules that apply to already-placed students."
)


@router.post("", response_model=PolicyIngestResponse)
async def create_policy(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> PolicyIngestResponse:
    source_text = await resolve_source_text(text, file)
    rules = extract_structured(source_text, PolicyRules, POLICY_INSTRUCTIONS)
    rules.allowed_branches = normalize_list(rules.allowed_branches, normalize_branch)
    rules.allowed_batches = normalize_list(rules.allowed_batches, normalize_batch)
    policy_id = make_document_id(source_text)
    upsert_policy(policy_id, source_text, rules.model_dump_json())
    ingest_document(COLLECTION_POLICIES, policy_id, "policy", source_text)
    return PolicyIngestResponse(id=policy_id, rules=rules)


@router.get("", response_model=list[PolicySummary])
def list_policies_endpoint() -> list[PolicySummary]:
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
def get_policy_endpoint(policy_id: str) -> PolicyDetail:
    row = get_policy(policy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return PolicyDetail(
        id=row["id"],
        rules=PolicyRules(**row["rules"]),
        source_text=row["source_text"],
    )
