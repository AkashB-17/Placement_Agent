"""
Keep the vector index in step with the database.

Postgres is the source of truth for policy and JD text; the Chroma index is derived data
used only to cite the clause behind a failed rule. Hosted servers often have a disk that
is wiped on every deploy or restart, so at startup any policy/JD with no chunks in the
index is re-embedded. It is idempotent (ingest deletes and re-adds a document's chunks)
and cheap: a document is only embedded when it is missing.
"""
from __future__ import annotations

import logging

from app import db
from app.services.chunking import CLAUSE_CHUNK_OVERLAP, CLAUSE_CHUNK_SIZE
from app.services.vectorstore import COLLECTION_JDS, COLLECTION_POLICIES, get_collection, ingest_document

logger = logging.getLogger("uvicorn.error")

_SOURCES = (
    (COLLECTION_POLICIES, "policy", db.list_policy_sources),
    (COLLECTION_JDS, "jd", db.list_jd_sources),
)


def _indexed(collection_name: str, doc_id: str) -> bool:
    found = get_collection(collection_name).get(where={"doc_id": doc_id}, limit=1, include=[])
    return bool(found["ids"])


def sync_index() -> dict[str, int]:
    """Embed every policy/JD that has no chunks in the index. Returns counts."""
    checked = rebuilt = 0
    for collection_name, doc_type, list_sources in _SOURCES:
        for doc_id, source_text in list_sources():
            checked += 1
            if _indexed(collection_name, doc_id):
                continue
            ingest_document(
                collection_name,
                doc_id,
                doc_type,
                source_text,
                chunk_size=CLAUSE_CHUNK_SIZE,
                chunk_overlap=CLAUSE_CHUNK_OVERLAP,
            )
            rebuilt += 1
    return {"checked": checked, "rebuilt": rebuilt}


def sync_index_quietly() -> None:
    """For startup: a failure is logged, never fatal (citations degrade, nothing else)."""
    try:
        counts = sync_index()
        logger.info("Vector index: %(checked)d documents checked, %(rebuilt)d re-embedded", counts)
    except Exception:
        logger.exception("Vector index sync failed; citations may be empty until the next restart")
