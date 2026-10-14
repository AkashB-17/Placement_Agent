from fastapi.testclient import TestClient

from app.schemas import PolicyRules
from app.services.vectorstore import COLLECTION_POLICIES, get_collection, ingest_document, retrieve


def test_reingest_same_document_does_not_duplicate_vectors(client: TestClient) -> None:
    text = (
        "Campus placement policy. Minimum CGPA 7. Eligible branches are CSE and ECE. "
        "Students may apply to at most five companies. Already placed students can sit "
        "only for roles whose CTC is at least twice their current offer."
    )
    doc_id = "policy-doc-1"

    first = ingest_document(COLLECTION_POLICIES, doc_id, "policy", text)
    count_after_first = get_collection(COLLECTION_POLICIES).count()
    second = ingest_document(COLLECTION_POLICIES, doc_id, "policy", text)
    count_after_second = get_collection(COLLECTION_POLICIES).count()

    assert first == second
    assert first > 0
    assert count_after_first == count_after_second == first

    records = get_collection(COLLECTION_POLICIES).get(include=["metadatas"])
    assert sorted(records["ids"]) == [f"{doc_id}:{index}" for index in range(first)]
    for metadata in records["metadatas"]:
        assert metadata["doc_id"] == doc_id
        assert metadata["doc_type"] == "policy"
        assert "chunk_index" in metadata


def test_retrieve_passes_k_and_returns_distance(client: TestClient) -> None:
    text = "Allowed branches: CSE. Minimum CGPA is 8. Max one backlog."
    ingest_document(COLLECTION_POLICIES, "policy-doc-2", "policy", text)
    hits = retrieve(COLLECTION_POLICIES, "minimum CGPA", k=1)
    assert len(hits) == 1
    assert "text" in hits[0]
    assert "metadata" in hits[0]
    assert "distance" in hits[0]
