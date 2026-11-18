"""Vector index rebuild: a wiped index (fresh server disk) is refilled from the database."""
from __future__ import annotations

import shutil

from app.config import get_settings
from app.schemas import JDRequirements, PolicyRules
from app.services import index_sync, vectorstore
from app.services.vectorstore import COLLECTION_JDS, COLLECTION_POLICIES, get_collection
from tests.conftest import fake_embed_texts
from tests.test_match import _post_jd, _post_policy

POLICY_TEXT_CLAUSES = 3


def _chunks(collection: str) -> int:
    return get_collection(collection).count()


def _wipe_index() -> None:
    """Simulate a fresh server disk: an empty index directory. (Deleting the folder isn't
    enough: Chroma keeps the open index in process memory.)"""
    settings = get_settings()
    settings.chroma_path = settings.chroma_path.parent / f"{settings.chroma_path.name}-fresh"
    shutil.rmtree(settings.chroma_path, ignore_errors=True)
    vectorstore.reset_clients()


def test_wiped_index_is_rebuilt_from_database(client, monkeypatch) -> None:
    _post_policy(client, monkeypatch, PolicyRules(min_cgpa=7.0))
    _post_jd(client, monkeypatch, JDRequirements(company="Acme", required_skills=["Python"]))
    before = (_chunks(COLLECTION_POLICIES), _chunks(COLLECTION_JDS))
    assert all(before)

    _wipe_index()
    assert (_chunks(COLLECTION_POLICIES), _chunks(COLLECTION_JDS)) == (0, 0)

    assert index_sync.sync_index() == {"checked": 2, "rebuilt": 2}
    assert (_chunks(COLLECTION_POLICIES), _chunks(COLLECTION_JDS)) == before  # same chunking as upload


def test_sync_skips_documents_already_indexed(client, monkeypatch) -> None:
    _post_policy(client, monkeypatch, PolicyRules())
    calls = []

    def counting_embed(texts):
        calls.append(texts)
        return fake_embed_texts(texts)

    monkeypatch.setattr("app.services.vectorstore.embed_texts", counting_embed)
    assert index_sync.sync_index() == {"checked": 1, "rebuilt": 0}
    assert calls == []


def test_sync_failure_is_not_fatal(client, monkeypatch, caplog) -> None:
    _post_policy(client, monkeypatch, PolicyRules())
    _wipe_index()

    def broken(_texts):
        raise RuntimeError("OpenAI down")

    monkeypatch.setattr("app.services.vectorstore.embed_texts", broken)
    index_sync.sync_index_quietly()  # must not raise
    assert "Vector index sync failed" in caplog.text
