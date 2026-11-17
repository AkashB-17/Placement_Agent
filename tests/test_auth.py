"""Real JWT verification against a local ES256 key; only the JWKS download is faked."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.config import set_settings
from app.db import upsert_profile
from app.main import check_startup_settings
from tests.conftest import make_test_settings

SUPABASE_URL = "https://testproj.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
KID = "test-key-1"
USER_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def auth_client(app_and_user, tmp_path, monkeypatch, signing_key):
    """Client with NO auth override, so requests go through verify_token."""
    app, _ = app_and_user
    app.dependency_overrides.clear()
    set_settings(make_test_settings(tmp_path, supabase_url=SUPABASE_URL))
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwks = {"keys": [{**jwk, "kid": KID, "alg": "ES256", "use": "sig"}]}
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: jwks)
    with TestClient(app) as test_client:
        yield test_client


def _token(key, **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": USER_ID,
        "email": "asha@example.com",
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + 3600,
        "role": "authenticated",
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": KID})


def _get(client, token, path="/admin/me"):
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


def test_valid_token_resolves_role_from_profiles(auth_client, signing_key) -> None:
    upsert_profile(USER_ID, "asha@example.com", role="officer")
    response = _get(auth_client, _token(signing_key))
    assert response.status_code == 200
    assert response.json() == {"id": USER_ID, "email": "asha@example.com", "role": "officer"}


def test_role_claims_in_token_are_ignored(auth_client, signing_key) -> None:
    # A user can write anything into user_metadata; only profiles.role counts.
    upsert_profile(USER_ID, "asha@example.com", role="student")
    token = _token(signing_key, user_metadata={"role": "admin"}, app_role="admin")
    assert _get(auth_client, token).json()["role"] == "student"
    assert _get(auth_client, token, "/students").status_code == 403


def test_missing_token_is_401(auth_client) -> None:
    response = auth_client.get("/admin/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"exp": int(time.time()) - 10}, "Token expired."),
        ({"aud": "anon"}, "Invalid token."),
        ({"iss": "https://evil.example.com/auth/v1"}, "Invalid token."),
    ],
)
def test_bad_claims_are_401(auth_client, signing_key, overrides, detail) -> None:
    upsert_profile(USER_ID, "asha@example.com", role="admin")
    response = _get(auth_client, _token(signing_key, **overrides))
    assert response.status_code == 401
    assert response.json()["detail"] == detail


def test_token_signed_by_another_key_is_401(auth_client) -> None:
    upsert_profile(USER_ID, "asha@example.com", role="admin")
    forged = _token(ec.generate_private_key(ec.SECP256R1()))
    assert _get(auth_client, forged).status_code == 401


def test_hs256_token_is_rejected(auth_client) -> None:
    # Algorithm-confusion guard: a shared-secret token must never be accepted.
    upsert_profile(USER_ID, "asha@example.com", role="admin")
    token = jwt.encode(
        {"sub": USER_ID, "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 60},
        "a-guessable-secret-of-at-least-32-bytes!!",
        algorithm="HS256",
        headers={"kid": KID},
    )
    assert _get(auth_client, token).status_code == 401


def test_garbage_token_is_401(auth_client) -> None:
    assert _get(auth_client, "not-a-jwt").status_code == 401


def test_valid_token_without_profile_is_403(auth_client, signing_key) -> None:
    assert _get(auth_client, _token(signing_key)).status_code == 403


def test_unreachable_jwks_is_503(auth_client, signing_key, monkeypatch) -> None:
    def _down(self):
        raise jwt.PyJWKClientConnectionError("network down")

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", _down)
    from app.auth import reset_jwks_clients

    reset_jwks_clients()
    upsert_profile(USER_ID, "asha@example.com", role="admin")
    assert _get(auth_client, _token(signing_key)).status_code == 503


def test_dev_bypass_acts_as_admin_on_sqlite(app_and_user, tmp_path) -> None:
    app, _ = app_and_user
    app.dependency_overrides.clear()
    set_settings(make_test_settings(tmp_path, dev_auth_bypass=True))
    with TestClient(app) as client:
        assert client.get("/admin/me").json()["role"] == "admin"


def test_dev_bypass_refused_with_postgres(tmp_path) -> None:
    from app.config import reset_settings

    set_settings(make_test_settings(tmp_path, dev_auth_bypass=True, database_url="postgresql://x"))
    try:
        with pytest.raises(RuntimeError, match="DEV_AUTH_BYPASS"):
            check_startup_settings()
    finally:
        reset_settings()
