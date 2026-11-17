"""Who may call what. Auth itself is covered in test_auth.py; here the user is injected."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings, set_settings
from app.db import get_profile, upsert_profile
from app.schemas import JDRequirements, ParsedResume, PolicyRules
from app.services import scoring, storage, supabase_admin
from app.services.scoring import EvidenceReport
from tests.conftest import make_test_settings

RESUME = b"Python developer. Built APIs with FastAPI."


@pytest.fixture
def seeded(client: TestClient, monkeypatch):
    """As admin: one policy, one JD, two students (one linked to asha@example.com)."""
    monkeypatch.setattr("app.routers.policies.extract_structured", lambda *a: PolicyRules())
    monkeypatch.setattr("app.routers.jds.extract_structured", lambda *a: JDRequirements(required_skills=["Python"]))
    monkeypatch.setattr("app.routers.students.extract_structured", lambda *a: ParsedResume(skills=["Python"]))
    monkeypatch.setattr(scoring, "extract_structured", lambda *a: EvidenceReport())
    monkeypatch.setattr("app.routers.match.retrieve", lambda *a, **k: [])

    def _student(name, email):
        form = {"name": name, "branch": "CSE", "batch": "2027", "cgpa": "8", "active_backlogs": "0", "email": email}
        resume = ("resume.txt", RESUME + name.encode(), "text/plain")
        return client.post("/students", data=form, files={"resume": resume}).json()["id"]

    return {
        "policy": client.post("/policies", data={"text": "policy"}).json()["id"],
        "jd": client.post("/jds", data={"text": "jd one"}).json()["id"],
        "asha": _student("Asha", "Asha@Example.com"),
        "ravi": _student("Ravi", "ravi@example.com"),
    }


# ── Matrix ───────────────────────────────────────────────────────────────────

def _calls(ids):
    return {
        "upload policy": ("post", "/policies", {"data": {"text": "new policy"}}),
        "upload jd": ("post", "/jds", {"data": {"text": "new jd"}}),
        "read policies": ("get", "/policies", {}),
        "read jds": ("get", "/jds", {}),
        "list students": ("get", "/students", {}),
        "read a student": ("get", f"/students/{ids['ravi']}", {}),
        "ranked": ("get", f"/jds/{ids['jd']}/ranked", {"params": {"policy_id": ids["policy"]}}),
        "invite": ("post", "/admin/invite", {"json": {"email": "x@example.com", "role": "officer"}}),
        "list users": ("get", "/admin/users", {}),
    }


ALLOWED = {
    "admin": {"upload policy", "upload jd", "read policies", "read jds", "list students", "read a student", "ranked", "invite", "list users"},
    "officer": {"upload policy", "upload jd", "read policies", "read jds", "list students", "read a student", "ranked"},
    "recruiter": {"upload jd", "read policies", "read jds"},
    "student": {"read policies", "read jds"},
}


@pytest.mark.parametrize("role", ["officer", "recruiter", "student"])
def test_role_matrix(client: TestClient, seeded, login_as, role) -> None:
    login_as(role, email=f"{role}@example.com")
    for name, (method, path, kwargs) in _calls(seeded).items():
        status = getattr(client, method)(path, **kwargs).status_code
        if name in ALLOWED[role]:
            assert status != 403, f"{role} should be allowed: {name}"
        else:
            assert status == 403, f"{role} should be forbidden: {name} (got {status})"


# ── Students see only themselves ─────────────────────────────────────────────

def test_student_me_matches_email_case_insensitively(client, seeded, login_as) -> None:
    login_as("student", email="asha@example.com")
    response = client.get("/students/me")
    assert response.status_code == 200
    assert response.json()["id"] == seeded["asha"]


def test_student_without_linked_record_gets_404(client, seeded, login_as) -> None:
    login_as("student", email="nobody@example.com")
    assert client.get("/students/me").status_code == 404


def test_student_can_match_self_but_not_others(client, seeded, login_as) -> None:
    login_as("student", email="asha@example.com")
    own = {"jd_id": seeded["jd"], "student_id": seeded["asha"], "policy_id": seeded["policy"]}
    assert client.post("/match", json=own).status_code == 200
    other = {**own, "student_id": seeded["ravi"]}
    assert client.post("/match", json=other).status_code == 404


def test_recruiter_cannot_overwrite_someone_elses_jd(client, seeded, login_as, monkeypatch) -> None:
    login_as("recruiter", email="hr@example.com")
    assert client.post("/jds", data={"text": "jd one"}).status_code == 403  # created by admin
    assert client.post("/jds", data={"text": "recruiter jd"}).status_code == 200


def test_staff_create_student_records_with_creator(client, seeded) -> None:
    from app.db import get_connection

    row = get_connection().execute("SELECT created_by, email FROM students WHERE id = ?", (seeded["asha"],)).fetchone()
    assert row["created_by"] == "00000000-0000-0000-0000-00000000000a"
    assert row["email"] == "asha@example.com"  # stored lower-cased


# ── Admin ────────────────────────────────────────────────────────────────────

def test_admin_invite_creates_user_and_sets_role(client, tmp_path, monkeypatch) -> None:
    set_settings(make_test_settings(tmp_path, supabase_url="https://p.supabase.co", supabase_secret_key="sb_secret_test"))
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers["apikey"]
        seen["body"] = json.loads(request.content)
        upsert_profile("22222222-2222-2222-2222-222222222222", "tpo@example.com")  # the auth trigger's job
        return httpx.Response(200, json={"id": "22222222-2222-2222-2222-222222222222"})

    monkeypatch.setattr(supabase_admin, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    response = client.post("/admin/invite", json={"email": "TPO@example.com", "role": "officer"})
    assert response.status_code == 200
    assert seen == {
        "url": "https://p.supabase.co/auth/v1/invite",
        "apikey": "sb_secret_test",
        "body": {"email": "tpo@example.com"},
    }
    assert get_profile("22222222-2222-2222-2222-222222222222")["role"] == "officer"


def test_invite_rejects_unknown_role(client) -> None:
    assert client.post("/admin/invite", json={"email": "a@b.c", "role": "superuser"}).status_code == 422


def test_admin_cannot_demote_self(client) -> None:
    upsert_profile("00000000-0000-0000-0000-00000000000a", "admin@test.local", role="admin")
    response = client.put("/admin/users/00000000-0000-0000-0000-00000000000a/role", json={"role": "student"})
    assert response.status_code == 409


def test_change_role(client) -> None:
    upsert_profile("33333333-3333-3333-3333-333333333333", "r@example.com")
    response = client.put("/admin/users/33333333-3333-3333-3333-333333333333/role", json={"role": "recruiter"})
    assert response.json()["role"] == "recruiter"
    assert client.put("/admin/users/nope/role", json={"role": "officer"}).status_code == 404


def test_admin_lists_users_with_roles(client) -> None:
    upsert_profile("44444444-4444-4444-4444-444444444444", "o@example.com", "officer")
    users = {u["email"]: u["role"] for u in client.get("/admin/users").json()}
    assert users["o@example.com"] == "officer"


# ── Resume storage ───────────────────────────────────────────────────────────

@pytest.fixture
def storage_calls(tmp_path, monkeypatch):
    set_settings(make_test_settings(tmp_path, supabase_url="https://p.supabase.co", supabase_secret_key="sb_secret_test"))
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "/object/sign/" in request.url.path:
            return httpx.Response(200, json={"signedURL": "/object/sign/resumes/abc?token=t0k"})
        return httpx.Response(200, json={"Key": "resumes/abc"})

    monkeypatch.setattr(storage, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return calls


def test_resume_uploaded_to_private_bucket_and_linked(client, seeded, storage_calls, login_as) -> None:
    form = {"name": "Mira", "branch": "CSE", "batch": "2027", "cgpa": "9", "active_backlogs": "0", "email": "mira@example.com"}
    student_id = client.post(
        "/students", data=form, files={"resume": ("Resume.PDF.txt", b"Mira. Python.", "text/plain")}
    ).json()["id"]

    upload = storage_calls[0]
    assert upload.method == "POST"
    assert upload.url.path.startswith(f"/storage/v1/object/resumes/{student_id}/")
    assert upload.url.path.endswith(".txt")
    assert upload.headers["x-upsert"] == "true"
    assert upload.headers["apikey"] == "sb_secret_test"
    assert upload.content == b"Mira. Python."

    link = client.get(f"/students/{student_id}/resume").json()
    assert link == {"url": "https://p.supabase.co/storage/v1/object/sign/resumes/abc?token=t0k", "expires_in": 60}
    assert json.loads(storage_calls[1].content) == {"expiresIn": 60}

    login_as("student", email="mira@example.com")
    assert client.get(f"/students/{student_id}/resume").status_code == 200
    login_as("student", email="someone@example.com")
    assert client.get(f"/students/{student_id}/resume").status_code == 404


def test_same_resume_same_object_path(client, storage_calls, monkeypatch) -> None:
    monkeypatch.setattr("app.routers.students.extract_structured", lambda *a: ParsedResume())
    form ={"name": "Mira", "branch": "CSE", "batch": "2027", "cgpa": "9", "active_backlogs": "0"}
    for _ in range(2):
        client.post("/students", data=form, files={"resume": ("r.txt", b"Mira. Python.", "text/plain")})
    assert storage_calls[0].url.path == storage_calls[1].url.path


def test_storage_failure_is_502_and_nothing_saved(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.routers.students.extract_structured", lambda *a: ParsedResume())
    set_settings(make_test_settings(tmp_path, supabase_url="https://p.supabase.co", supabase_secret_key="sb_secret_test"))
    monkeypatch.setattr(
        storage, "_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))),
    )
    form = {"name": "Mira", "branch": "CSE", "batch": "2027", "cgpa": "9", "active_backlogs": "0"}
    response = client.post("/students", data=form, files={"resume": ("r.txt", b"Mira. Python.", "text/plain")})
    assert response.status_code == 502
    assert client.get("/students").json() == []


def test_no_storage_configured_keeps_text_only(client, seeded) -> None:
    assert get_settings().supabase_url == ""
    detail = client.get(f"/students/{seeded['asha']}").json()
    assert detail["has_resume_file"] is False
    assert client.get(f"/students/{seeded['asha']}/resume").status_code == 404
