"""Score cache: a ranking is scored by the AI once; any change to a scoring input re-scores."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.schemas import JDRequirements, PolicyRules
from app.services import scoring
from tests.test_match import _evidence_from_resume, _post_jd, _post_policy, _post_student

JD = JDRequirements(company="Acme", role="SDE", required_skills=["Python", "FastAPI"], preferred_skills=["SQL"])


@pytest.fixture
def llm_calls(monkeypatch):
    """Counts scoring LLM calls (the fake answers from the resume text)."""
    calls = []

    def counting(text, schema, instructions):
        calls.append(text)
        return _evidence_from_resume(text, schema, instructions)

    monkeypatch.setattr(scoring, "extract_structured", counting)
    monkeypatch.setattr("app.services.matching.retrieve", lambda *a, **k: [])
    return calls


@pytest.fixture
def ranked_world(client: TestClient, monkeypatch, llm_calls):
    ids = {
        "policy": _post_policy(client, monkeypatch, PolicyRules(min_cgpa=7.0, max_active_backlogs=0)),
        "jd": _post_jd(client, monkeypatch, JD),
    }
    _post_student(client, monkeypatch, "Alice", "strong")
    _post_student(client, monkeypatch, "Bob", "partial")
    _post_student(client, monkeypatch, "Carol", "strong", active_backlogs=1)  # ineligible: never scored
    return ids


def _rank(client, ids, **params):
    response = client.get(f"/jds/{ids['jd']}/ranked", params={"policy_id": ids["policy"], **params})
    assert response.status_code == 200, response.json()
    return response.json()


def test_second_ranking_makes_no_ai_calls(client, ranked_world, llm_calls) -> None:
    first = _rank(client, ranked_world)
    assert len(llm_calls) == 2  # Alice and Bob; Carol is ineligible
    assert (first["ai_calls"], first["cached_scores"]) == (2, 0)

    second = _rank(client, ranked_world)
    assert len(llm_calls) == 2
    assert (second["ai_calls"], second["cached_scores"]) == (0, 2)
    assert [r["score_breakdown"] for r in second["eligible"]] == [r["score_breakdown"] for r in first["eligible"]]
    assert {r["score_source"] for r in second["eligible"]} == {"cache"}
    assert second["ineligible"][0]["score_source"] is None


def test_refresh_rescores_and_overwrites(client, ranked_world, llm_calls) -> None:
    _rank(client, ranked_world)
    refreshed = _rank(client, ranked_world, refresh="true")
    assert len(llm_calls) == 4
    assert refreshed["ai_calls"] == 2
    assert db.count_cached_scores() == 2  # replaced, not duplicated


def test_match_and_ranking_share_the_cache(client, ranked_world, llm_calls) -> None:
    _rank(client, ranked_world)
    alice = next(s["id"] for s in client.get("/students").json() if s["name"] == "Alice")
    data = client.post("/match", json={"jd_id": ranked_world["jd"], "student_id": alice, "policy_id": ranked_world["policy"]}).json()
    assert data["score_source"] == "cache"
    assert len(llm_calls) == 2


def test_eligibility_is_never_cached(client, ranked_world, llm_calls, monkeypatch) -> None:
    _rank(client, ranked_world)
    stricter = _post_policy(client, monkeypatch, PolicyRules(min_cgpa=9.0))
    data = _rank(client, {**ranked_world, "policy": stricter})
    assert data["eligible"] == []  # everyone's CGPA is 8.5: the new policy applies at once
    assert len(llm_calls) == 2


def test_new_resume_or_jd_skills_miss_the_cache(client, ranked_world, llm_calls, monkeypatch) -> None:
    _rank(client, ranked_world)
    other_jd = _post_jd(client, monkeypatch, JDRequirements(company="Acme", role="SDE", required_skills=["Python"]))
    _rank(client, {**ranked_world, "jd": other_jd})
    assert len(llm_calls) == 4  # different skill list -> different prompt -> new key


def test_model_change_misses_the_cache(client, ranked_world, llm_calls) -> None:
    _rank(client, ranked_world)
    get_settings().openai_chat_model = "some-newer-model"
    data = _rank(client, ranked_world)
    assert data["ai_calls"] == 2


def test_scoring_version_is_part_of_the_key(monkeypatch) -> None:
    before = scoring.score_cache_key("resume", JD)
    monkeypatch.setattr(scoring, "SCORING_VERSION", scoring.SCORING_VERSION + "-next")
    assert scoring.score_cache_key("resume", JD) != before


def test_no_required_skills_needs_no_call_or_cache(client, ranked_world, llm_calls, monkeypatch) -> None:
    empty_jd = _post_jd(client, monkeypatch, JDRequirements(company="Acme", preferred_skills=["SQL"]))
    data = _rank(client, {**ranked_world, "jd": empty_jd})
    assert llm_calls == [] and data["ai_calls"] == 0
    assert {r["score_source"] for r in data["eligible"]} == {"none"}
    assert db.count_cached_scores() == 0
