"""Error handling for ingestion: config, OpenAI failures, uploads, input validation, GET endpoints."""
from types import SimpleNamespace

import httpx
import openai
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.schemas import JDRequirements, ParsedResume, PolicyRules
from app.services import embeddings, llm

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _raising_client(exc: Exception):
    """A stand-in for openai.OpenAI whose chat and embedding calls raise `exc`."""

    def _raise(*_args, **_kwargs):
        raise exc

    def _factory(api_key: str):
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=_raise)),
            embeddings=SimpleNamespace(create=_raise),
        )

    return _factory


# ── Config ───────────────────────────────────────────────────────────────────

def test_api_key_defaults_to_empty(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert Settings(_env_file=None).openai_api_key == ""


def test_missing_api_key_is_reported(client: TestClient) -> None:
    from app.config import get_settings

    get_settings().openai_api_key = ""
    with pytest.raises(HTTPException) as info:
        llm.extract_structured("text", PolicyRules, "instructions")
    assert info.value.status_code == 500


# ── OpenAI failures -> 502 without leaking the key ───────────────────────────

@pytest.mark.parametrize(
    "exc",
    [
        openai.AuthenticationError(
            "bad key test-key", response=httpx.Response(401, request=_REQUEST), body=None
        ),
        openai.RateLimitError(
            "slow down", response=httpx.Response(429, request=_REQUEST), body=None
        ),
        openai.APIConnectionError(request=_REQUEST),
        openai.InternalServerError(
            "boom", response=httpx.Response(500, request=_REQUEST), body=None
        ),
    ],
)
def test_llm_upstream_errors_become_502(client: TestClient, monkeypatch, exc) -> None:
    monkeypatch.setattr(llm, "OpenAI", _raising_client(exc))
    with pytest.raises(HTTPException) as info:
        llm.extract_structured("text", PolicyRules, "instructions")
    assert info.value.status_code == 502
    assert "test-key" not in info.value.detail


def test_embedding_upstream_error_becomes_502(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(llm, "OpenAI", _raising_client(openai.APIConnectionError(request=_REQUEST)))
    with pytest.raises(HTTPException) as info:
        embeddings.embed_texts(["hello"])
    assert info.value.status_code == 502


def test_post_policy_returns_502_on_openai_outage(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(llm, "OpenAI", _raising_client(openai.APIConnectionError(request=_REQUEST)))
    response = client.post("/policies", data={"text": "Minimum CGPA 7."})
    assert response.status_code == 502


# ── text / file resolution ───────────────────────────────────────────────────

def test_text_and_file_together_rejected(client: TestClient) -> None:
    response = client.post(
        "/policies",
        data={"text": "inline policy"},
        files={"file": ("policy.txt", b"file policy", "text/plain")},
    )
    assert response.status_code == 422
    assert "not both" in response.json()["detail"]


def test_neither_text_nor_file_rejected(client: TestClient) -> None:
    assert client.post("/policies", data={}).status_code == 400


def test_empty_file_with_text_uses_text(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.routers.policies.extract_structured", lambda *a: PolicyRules())
    response = client.post(
        "/policies",
        data={"text": "inline policy"},
        files={"file": ("", b"", "application/octet-stream")},
    )
    assert response.status_code == 200


def test_unsupported_file_type_rejected(client: TestClient) -> None:
    response = client.post("/jds", files={"file": ("jd.docx", b"PK\x03\x04", "application/zip")})
    assert response.status_code == 415


def test_corrupt_pdf_is_422(client: TestClient) -> None:
    response = client.post("/jds", files={"file": ("jd.pdf", b"not really a pdf", "application/pdf")})
    assert response.status_code == 422


def test_non_utf8_text_is_422(client: TestClient) -> None:
    response = client.post("/jds", files={"file": ("jd.txt", b"\xff\xfe\xfa bad", "text/plain")})
    assert response.status_code == 422


# ── Normalization at ingest ──────────────────────────────────────────────────

def test_policy_and_jd_branches_batches_normalized(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routers.policies.extract_structured",
        lambda *a: PolicyRules(
            allowed_branches=["Computer Science and Engineering", "ECE", "cse"],
            allowed_batches=["2023-2027"],
        ),
    )
    policy = client.post("/policies", data={"text": "policy"}).json()
    assert policy["rules"]["allowed_branches"] == ["CSE", "ECE"]
    assert policy["rules"]["allowed_batches"] == ["2027"]

    monkeypatch.setattr(
        "app.routers.jds.extract_structured",
        lambda *a: JDRequirements(allowed_branches=["Information Technology"], allowed_batches=["Class of 2027"]),
    )
    jd = client.post("/jds", data={"text": "jd"}).json()
    assert jd["requirements"]["allowed_branches"] == ["IT"]
    assert jd["requirements"]["allowed_batches"] == ["2027"]


# ── /students input ──────────────────────────────────────────────────────────

def _student_form(**overrides) -> dict[str, str]:
    form = {"name": "Ada", "branch": "CSE", "batch": "2026", "cgpa": "8.0", "active_backlogs": "0"}
    form.update(overrides)
    return form


def test_student_accepts_txt_resume_and_is_placed(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.routers.students.extract_structured", lambda *a: ParsedResume(skills=["Python"]))
    response = client.post(
        "/students",
        data=_student_form(is_placed="true"),
        files={"resume": ("resume.txt", b"Python developer", "text/plain")},
    )
    assert response.status_code == 200
    student_id = response.json()["id"]
    detail = client.get(f"/students/{student_id}").json()
    assert detail["profile"]["is_placed"] is True
    assert detail["resume_text"] == "Python developer"


@pytest.mark.parametrize("overrides", [{"cgpa": "11"}, {"cgpa": "-1"}, {"active_backlogs": "-2"}, {"branch": "  "}])
def test_student_invalid_fields_are_422(client: TestClient, overrides) -> None:
    response = client.post(
        "/students",
        data=_student_form(**overrides),
        files={"resume": ("resume.txt", b"Python developer", "text/plain")},
    )
    assert response.status_code == 422


def test_student_unsupported_resume_type_is_415(client: TestClient) -> None:
    response = client.post(
        "/students",
        data=_student_form(),
        files={"resume": ("resume.docx", b"PK\x03\x04", "application/zip")},
    )
    assert response.status_code == 415


# ── GET list / detail ────────────────────────────────────────────────────────

def test_list_and_get_endpoints(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.routers.policies.extract_structured", lambda *a: PolicyRules(min_cgpa=7.0))
    monkeypatch.setattr("app.routers.jds.extract_structured", lambda *a: JDRequirements(company="Acme"))
    policy_id = client.post("/policies", data={"text": "policy"}).json()["id"]
    jd_id = client.post("/jds", data={"text": "jd"}).json()["id"]

    assert [p["id"] for p in client.get("/policies").json()] == [policy_id]
    assert client.get(f"/policies/{policy_id}").json()["rules"]["min_cgpa"] == 7.0
    assert [j["id"] for j in client.get("/jds").json()] == [jd_id]
    assert client.get(f"/jds/{jd_id}").json()["requirements"]["company"] == "Acme"
    assert client.get("/students").json() == []


@pytest.mark.parametrize("path", ["/policies/nope", "/jds/nope", "/students/nope"])
def test_get_unknown_id_is_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404
