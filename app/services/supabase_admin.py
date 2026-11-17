"""
Supabase Auth admin calls (secret key, server only).

Inviting creates the auth user immediately and emails them a link to set a password.
The auth trigger creates their profile with role 'student'; the caller then sets the
real role. This is how privileged roles are granted: never through open sign-up.
"""
from __future__ import annotations

import httpx
from fastapi import HTTPException

from app.config import get_settings

_TIMEOUT = 30.0


def _http_client() -> httpx.Client:
    """Separate function so tests can swap in an httpx.MockTransport."""
    return httpx.Client(timeout=_TIMEOUT)


def invite_user(email: str) -> str:
    """Invite `email` and return the new auth user's id."""
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_secret_key):
        raise HTTPException(status_code=500, detail="Supabase is not configured.")
    key = settings.supabase_secret_key
    try:
        with _http_client() as client:
            response = client.post(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/invite",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                json={"email": email},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach Supabase Auth.") from exc
    if response.status_code == 422:
        raise HTTPException(status_code=409, detail="A user with this email already exists.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Supabase Auth error {response.status_code}.")
    user_id = response.json().get("id")
    if not user_id:
        raise HTTPException(status_code=502, detail="Supabase Auth returned no user id.")
    return user_id
