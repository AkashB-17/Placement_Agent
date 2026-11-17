"""Extracted rules are only enforced if the source document states them."""
from fastapi.testclient import TestClient

from app.schemas import JDRequirements, PolicyRules
from app.services.grounding import ground_jd, ground_policy

JD_TEXT = (
    "Role: Data Scientist\n"
    "Minimum CGPA of 8.5 is required for this role.\n"
    "Open to branches: CSE, AI-ML, IT.\n"
    "Application Deadline: November 25, 2026."
)


def test_deadline_year_is_not_a_batch():
    jd = JDRequirements(allowed_batches=["2026"], min_cgpa_override=8.5)
    warnings = ground_jd(jd, JD_TEXT)
    assert jd.allowed_batches == []
    assert jd.min_cgpa_override == 8.5
    assert len(warnings) == 1 and "2026" in warnings[0]


def test_stated_batch_is_kept_including_ranges():
    for text in ("Only the 2027 graduating batch is eligible.", "Open to the 2023-27 batch.", "Class of 2027 only."):
        policy = PolicyRules(allowed_batches=["2027"])
        assert ground_policy(policy, text) == []
        assert policy.allowed_batches == ["2027"]


def test_unstated_cgpa_is_dropped():
    policy = PolicyRules(min_cgpa=7.5)
    warnings = ground_policy(policy, "Minimum CGPA of 7.0 on a 10-point scale.")
    assert policy.min_cgpa is None
    assert warnings


def test_cgpa_number_formats():
    for value, text in ((7.0, "CGPA 7 or above"), (7.0, "CGPA of 7.00"), (8.5, "at least 8.50 CGPA")):
        policy = PolicyRules(min_cgpa=value)
        ground_policy(policy, text)
        assert policy.min_cgpa == value, (value, text)
    policy = PolicyRules(min_cgpa=7.0)
    ground_policy(policy, "CGPA 17.0 or 7.5")
    assert policy.min_cgpa is None


def test_ingest_returns_grounding_warnings(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routers.jds.extract_structured",
        lambda *a: JDRequirements(allowed_batches=["2026"], min_cgpa_override=8.5),
    )
    payload = client.post("/jds", data={"text": JD_TEXT}).json()
    assert payload["requirements"]["allowed_batches"] == []
    assert payload["requirements"]["min_cgpa_override"] == 8.5
    assert payload["warnings"]
