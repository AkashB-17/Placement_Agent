from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from app.config import get_settings
from app.services.chunking import CHUNK_OVERLAP, CHUNK_SIZE, chunk_text
from app.services.embeddings import embed_texts

COLLECTION_POLICIES = "policies"
COLLECTION_JDS = "jds"
COLLECTION_RESUMES = "resumes"

_clients: dict[str, ClientAPI] = {}


def _client() -> ClientAPI:
    path = str(get_settings().chroma_path)
    if path not in _clients:
        _clients[path] = chromadb.PersistentClient(path=path)
    return _clients[path]


def reset_clients() -> None:
    _clients.clear()
    _query_embeddings.clear()


def get_collection(name: str) -> Collection:
    return _client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )


def ingest_document(
    collection_name: str,
    doc_id: str,
    doc_type: str,
    text: str,
    extra_metadata: dict[str, Any] | None = None,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> int:
    chunks = chunk_text(text, chunk_size, chunk_overlap)
    if not chunks:
        return 0

    # Compute embeddings BEFORE deleting old vectors so a transient
    # embedding failure leaves existing data intact.
    embeddings = embed_texts(chunks)

    collection = get_collection(collection_name)
    collection.delete(where={"doc_id": doc_id})

    ids = [f"{doc_id}:{index}" for index in range(len(chunks))]
    metadatas: list[dict[str, Any]] = []
    for index in range(len(chunks)):
        metadata: dict[str, Any] = {
            "doc_id": doc_id,
            "doc_type": doc_type,
            "chunk_index": index,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        metadatas.append(metadata)

    collection.upsert(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(chunks)


# Citation queries are a handful of fixed rule descriptions, so their embeddings are
# computed once per process instead of one OpenAI call per failed rule.
_QUERY_CACHE_SIZE = 256
_query_embeddings: dict[str, list[float]] = {}


def _embed_query(query: str) -> list[float]:
    cached = _query_embeddings.get(query)
    if cached is None:
        cached = embed_texts([query])[0]
        if len(_query_embeddings) >= _QUERY_CACHE_SIZE:
            _query_embeddings.clear()
        _query_embeddings[query] = cached
    return cached


def retrieve(
    collection: str,
    query: str,
    k: int,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    query_embedding = _embed_query(query)
    result = get_collection(collection).query(
        query_embeddings=[query_embedding],
        n_results=k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    documents = (result.get("documents") or [[]])[0] or []
    metadatas = (result.get("metadatas") or [[]])[0] or []
    distances = (result.get("distances") or [[]])[0] or []
    hits: list[dict[str, Any]] = []
    for text, metadata, distance in zip(documents, metadatas, distances):
        hits.append({"text": text, "metadata": metadata, "distance": distance})
    return hits
