"""Speed-ups must not change behaviour: role cache invalidation, embedding cache, parallel ranking."""
import pytest

from app import db
from app.services import vectorstore


@pytest.fixture
def fake_postgres_profiles(monkeypatch):
    """Pretend to be on Postgres and count profile reads (no real database involved)."""
    reads = []
    roles = {"u1": "officer"}

    def get_profile(user_id):
        reads.append(user_id)
        return {"id": user_id, "email": "u1@example.com", "full_name": None, "role": roles[user_id]} if user_id in roles else None

    monkeypatch.setattr(db, "using_postgres", lambda: True)
    monkeypatch.setattr(db, "get_profile", get_profile)
    monkeypatch.setattr(db, "_execute", lambda query, params=(): roles.__setitem__(params[1], params[0]))
    db.clear_profile_cache()
    yield reads
    db.clear_profile_cache()


def test_profile_cached_between_requests(fake_postgres_profiles) -> None:
    assert db.get_profile_cached("u1")["role"] == "officer"
    assert db.get_profile_cached("u1")["role"] == "officer"
    assert fake_postgres_profiles == ["u1"]


def test_role_change_through_api_clears_cache(fake_postgres_profiles) -> None:
    db.get_profile_cached("u1")
    db.set_profile_role("u1", "student")
    assert db.get_profile_cached("u1")["role"] == "student"


def test_profile_cache_expires(fake_postgres_profiles, monkeypatch) -> None:
    db.get_profile_cached("u1")
    monkeypatch.setattr(db.time, "monotonic", lambda: 10**9)
    db.get_profile_cached("u1")
    assert fake_postgres_profiles == ["u1", "u1"]


def test_missing_profile_not_cached(fake_postgres_profiles) -> None:
    assert db.get_profile_cached("nobody") is None
    assert db.get_profile_cached("nobody") is None
    assert fake_postgres_profiles == ["nobody", "nobody"]


def test_sqlite_profiles_are_not_cached(client) -> None:
    db.upsert_profile("u2", "u2@example.com", "officer")
    db.get_profile_cached("u2")
    db.upsert_profile("u2", "u2@example.com", "recruiter")
    assert db.get_profile_cached("u2")["role"] == "recruiter"


def test_citation_query_embedded_once(client, monkeypatch) -> None:
    calls = []

    def counting_embed(texts):
        calls.append(list(texts))
        return [[0.1] * 8 for _ in texts]

    monkeypatch.setattr(vectorstore, "embed_texts", counting_embed)
    vectorstore.retrieve(vectorstore.COLLECTION_POLICIES, "minimum CGPA required", k=2)
    vectorstore.retrieve(vectorstore.COLLECTION_POLICIES, "minimum CGPA required", k=2)
    assert calls == [["minimum CGPA required"]]
