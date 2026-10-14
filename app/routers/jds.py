from fastapi import APIRouter, File, Form, UploadFile

from app.db import make_document_id, upsert_jd
from app.schemas import JDIngestResponse, JDRequirements
from app.services.llm import extract_structured
from app.services.pdf import resolve_source_text
from app.services.vectorstore import COLLECTION_JDS, ingest_document

router = APIRouter(prefix="/jds", tags=["jds"])

JD_INSTRUCTIONS = (
    "Extract job description requirements. "
    "Capture company, role, required skills, preferred skills, any CGPA override, "
    "allowed branches, CTC, deadline, and experience required."
)


@router.post("", response_model=JDIngestResponse)
async def create_jd(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> JDIngestResponse:
    source_text = await resolve_source_text(text, file)
    requirements = extract_structured(source_text, JDRequirements, JD_INSTRUCTIONS)
    jd_id = make_document_id(source_text)
    upsert_jd(jd_id, source_text, requirements.model_dump_json())
    ingest_document(COLLECTION_JDS, jd_id, "jd", source_text)
    return JDIngestResponse(id=jd_id, requirements=requirements)
