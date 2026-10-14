from fastapi import APIRouter, File, Form, UploadFile

from app.db import make_document_id, upsert_policy
from app.schemas import PolicyIngestResponse, PolicyRules
from app.services.llm import extract_structured
from app.services.pdf import resolve_source_text
from app.services.vectorstore import COLLECTION_POLICIES, ingest_document

router = APIRouter(prefix="/policies", tags=["policies"])

POLICY_INSTRUCTIONS = (
    "Extract campus placement policy rules. "
    "Capture minimum CGPA, maximum active backlogs, allowed branches, allowed batches, "
    "maximum applications per student, and any rules that apply to already-placed students."
)


@router.post("", response_model=PolicyIngestResponse)
async def create_policy(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> PolicyIngestResponse:
    source_text = await resolve_source_text(text, file)
    rules = extract_structured(source_text, PolicyRules, POLICY_INSTRUCTIONS)
    policy_id = make_document_id(source_text)
    upsert_policy(policy_id, source_text, rules.model_dump_json())
    ingest_document(COLLECTION_POLICIES, policy_id, "policy", source_text)
    return PolicyIngestResponse(id=policy_id, rules=rules)
