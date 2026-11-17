"""
Authentication and role checks.

Supabase Auth signs each user's access token (a JWT) with the project's asymmetric
signing key. We verify the signature against the public keys Supabase publishes (JWKS),
plus expiry, audience and issuer, so no shared secret lives in this service.

The role is read from public.profiles on every request, not from the token: profiles is
the single source of truth, a role change takes effect immediately, and user_metadata
(which users can edit themselves) is never consulted.

The backend talks to the database with the secret key, which bypasses RLS, so every
endpoint must declare who may call it with require_role(...).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.db import get_profile_cached

ROLES = ("student", "officer", "recruiter", "admin")
STAFF = ("officer", "admin")
_ALGORITHMS = ["ES256", "RS256"]
_AUDIENCE = "authenticated"

_bearer = HTTPBearer(auto_error=False, description="Supabase access token (see scripts/get_token.py)")
_jwks_clients: dict[str, jwt.PyJWKClient] = {}


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    role: str


def _auth_base_url() -> str:
    url = get_settings().supabase_url.rstrip("/")
    if not url:
        raise HTTPException(status_code=500, detail="SUPABASE_URL is not configured.")
    return f"{url}/auth/v1"


def get_jwks_client() -> jwt.PyJWKClient:
    jwks_url = f"{_auth_base_url()}/.well-known/jwks.json"
    if jwks_url not in _jwks_clients:
        # Keys are cached in-process; Supabase rotates them rarely.
        _jwks_clients[jwks_url] = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600)
    return _jwks_clients[jwks_url]


def reset_jwks_clients() -> None:
    _jwks_clients.clear()


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def verify_token(token: str) -> dict:
    """Return the verified claims, or raise 401 (bad token) / 503 (Auth unreachable)."""
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS,
            audience=_AUDIENCE,
            issuer=_auth_base_url(),
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(status_code=503, detail="Could not reach Supabase Auth.") from exc
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Token expired.") from exc
    except (jwt.PyJWKClientError, jwt.InvalidTokenError) as exc:
        raise _unauthorized("Invalid token.") from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> CurrentUser:
    if get_settings().dev_auth_bypass:
        return CurrentUser(id="dev-admin", email=None, role="admin")
    if credentials is None:
        raise _unauthorized("Not authenticated.")

    claims = verify_token(credentials.credentials)
    profile = get_profile_cached(claims["sub"])
    if profile is None:
        raise HTTPException(status_code=403, detail="No profile for this user.")
    return CurrentUser(
        id=claims["sub"],
        # The token's email is the one Supabase verified; it links a student to their record.
        email=claims.get("email") or profile.get("email"),
        role=profile["role"],
    )


def require_role(*roles: str) -> Callable[..., CurrentUser]:
    unknown = set(roles) - set(ROLES)
    if unknown:
        raise ValueError(f"Unknown roles: {unknown}")

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(roles)}.")
        return user

    return dependency


any_user = require_role(*ROLES)
staff_only = require_role(*STAFF)
