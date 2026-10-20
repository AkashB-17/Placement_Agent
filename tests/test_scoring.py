"""Coverage math, quote validation and reconciliation against the JD skill list. LLM mocked."""
import pytest

from app.schemas import JDRequirements
from app.services import scoring
from app.services.scoring import (
    EvidenceReport,
    SkillEvidence,
    compute_score,
    quote_in_resume,
    quote_mentions_skill,
    score_student,
)

RESUME = (
    "Backend developer. Built REST APIs in Python using FastAPI.\n"
    "Designed PostgreSQL schemas and wrote SQL\nqueries. Dockerized services."
)
STUDENT = {"id": "s1", "name": "Alice", "resume_text": RESUME}


def _mock_llm(monkeypatch, claims: dict[str, str | None]):
    """claims: skill -> quote (None = not evidenced). Skills not in the dict are omitted."""
    seen = {}

    def _fake(text, schema, instructions):
        seen["text"] = text
        return EvidenceReport(
            skills=[
                SkillEvidence(skill=skill, evidenced=quote is not None, evidence_quote=quote)
                for skill, quote in claims.items()
            ]
        )

    monkeypatch.setattr(scoring, "extract_structured", _fake)
    return seen


# ── Pure math ────────────────────────────────────────────────────────────────

def test_compute_score_weights():
    assert compute_score(1.0, 1.0) == 100.0
    assert compute_score(0.5, 1.0) == pytest.approx(62.5)  # 0.75*0.5 + 0.25*1
    assert compute_score(1.0, 0.0) == pytest.approx(75.0)


def test_compute_score_without_preferred_uses_required_only():
    assert compute_score(0.5, None) == pytest.approx(50.0)


def test_compute_score_without_required_is_none():
    assert compute_score(None, 1.0) is None


# ── Quote checks ─────────────────────────────────────────────────────────────

def test_quote_matches_across_line_breaks_and_case():
    assert quote_in_resume("wrote sql queries", RESUME)


def test_fabricated_quote_rejected():
    assert not quote_in_resume("Led a Kubernetes migration", RESUME)


@pytest.mark.parametrize(
    ("quote", "skill", "expected"),
    [
        ("Built REST APIs in Python", "Python", True),
        ("Built REST APIs in Python", "REST API", True),
        ("Dockerized services", "Docker", True),
        ("Built REST APIs in Python", "Rust", False),
        ("Built REST APIs in Python", "Go", False),
        ("Designed PostgreSQL schemas and wrote SQL", "Data Structures and Algorithms", False),
    ],
)
def test_quote_mentions_skill(quote, skill, expected):
    assert quote_mentions_skill(quote, skill) is expected


# ── score_student ────────────────────────────────────────────────────────────

def test_full_match_scores_100_with_evidence(monkeypatch):
    seen = _mock_llm(monkeypatch, {"Python": "REST APIs in Python", "FastAPI": "using FastAPI", "Docker": "Dockerized services"})
    jd = JDRequirements(required_skills=["Python", "FastAPI"], preferred_skills=["Docker"])
    result = score_student(STUDENT, jd)
    assert result.score == 100.0
    assert result.matched_required == ["Python", "FastAPI"]
    assert result.matched_preferred == ["Docker"]
    assert {e.skill for e in result.evidence} == {"Python", "FastAPI", "Docker"}
    assert seen["text"] == RESUME  # full resume, not retrieved chunks


def test_partial_coverage_math(monkeypatch):
    _mock_llm(monkeypatch, {"Python": "in Python", "Rust": None, "Docker": None, "SQL": "wrote SQL"})
    jd = JDRequirements(required_skills=["Python", "Rust"], preferred_skills=["Docker", "SQL"])
    result = score_student(STUDENT, jd)
    # required 1/2, preferred 1/2 -> 100 * (0.375 + 0.125) = 50
    assert result.score == pytest.approx(50.0)
    assert result.missing_required == ["Rust"]
    assert result.missing_preferred == ["Docker"]


def test_hallucinated_quote_downgraded(monkeypatch):
    _mock_llm(monkeypatch, {"Kubernetes": "Led a Kubernetes migration"})
    result = score_student(STUDENT, JDRequirements(required_skills=["Kubernetes"]))
    assert result.score == 0.0
    assert result.missing_required == ["Kubernetes"]
    assert result.evidence == []


def test_real_but_unrelated_quote_downgraded(monkeypatch):
    _mock_llm(monkeypatch, {"Rust": "Built REST APIs in Python"})
    result = score_student(STUDENT, JDRequirements(required_skills=["Rust"]))
    assert result.missing_required == ["Rust"]


def test_evidenced_without_quote_downgraded(monkeypatch):
    _mock_llm(monkeypatch, {"Python": None})
    monkeypatch.setattr(
        scoring,
        "extract_structured",
        lambda *a: EvidenceReport(skills=[SkillEvidence(skill="Python", evidenced=True, evidence_quote=None)]),
    )
    assert score_student(STUDENT, JDRequirements(required_skills=["Python"])).score == 0.0


def test_skill_omitted_by_llm_counts_as_missing(monkeypatch):
    # LLM silently drops "Rust"; coverage must be 1/2, not 1/1.
    _mock_llm(monkeypatch, {"Python": "in Python"})
    result = score_student(STUDENT, JDRequirements(required_skills=["Python", "Rust"]))
    assert result.score == pytest.approx(50.0)
    assert result.missing_required == ["Rust"]


def test_extra_skills_from_llm_are_ignored(monkeypatch):
    _mock_llm(monkeypatch, {"Python": "in Python", "FastAPI": "using FastAPI"})
    result = score_student(STUDENT, JDRequirements(required_skills=["Python"]))
    assert result.matched_required == ["Python"]
    assert [e.skill for e in result.evidence] == ["Python"]


def test_skill_in_both_lists_counts_once_as_required(monkeypatch):
    _mock_llm(monkeypatch, {"Python": "in Python"})
    result = score_student(STUDENT, JDRequirements(required_skills=["Python"], preferred_skills=["python"]))
    assert result.score == 100.0
    assert result.matched_preferred == []


def test_no_required_skills_gives_null_score_without_llm_call(monkeypatch):
    def _boom(*a):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(scoring, "extract_structured", _boom)
    result = score_student(STUDENT, JDRequirements(preferred_skills=["Docker"]))
    assert result.score is None
