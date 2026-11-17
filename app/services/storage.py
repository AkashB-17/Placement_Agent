"""
Resume files in a private Supabase Storage bucket, via the Storage REST API.

Files are uploaded from memory with the secret key and never written to local disk.
Object paths are content-addressed (<student_id>/<sha256 prefix>.<ext>), so each resume
version gets its own immutable path that a future application can pin.
Reading back is only through short-lived signed URLs.

When Supabase isn't configured (offline SQLite demo) storage is disabled and only the
extracted text is kept.
"""
from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

import httpx
from fastapi import HTTPException

from app.config import get_settings

_CONTENT_TYPES = {".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8"}
_TIMEOUT = 30.0


def storage_enabled() -> bool:
    settings = get_settings()
    return bool(settings.supabase_url and settings.supabase_secret_key)


def _http_client() -> httpx.Client:
    """Separate function so tests can swap in an httpx.MockTransport."""
    return httpx.Client(timeout=_TIMEOUT)


def _headers() -> dict[str, str]:
    key = get_settings().supabase_secret_key
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _base() -> str:
    return f"{get_settings().supabase_url.rstrip('/')}/storage/v1"


def resume_object_path(student_id: str, filename: str | None, data: bytes) -> str:
    suffix = PurePosixPath((filename or "").lower()).suffix or ".bin"
    return f"{student_id}/{hashlib.sha256(data).hexdigest()[:16]}{suffix}"


def _request(method: str, url: str, extra_headers: dict[str, str] | None = None, **kwargs) -> httpx.Response:
    headers = {**_headers(), **(extra_headers or {})}
    try:
        with _http_client() as client:
            response = client.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach Supabase Storage.") from exc
    if response.status_code >= 400:
        # Status only: the body can echo request details.
        raise HTTPException(status_code=502, detail=f"Supabase Storage error {response.status_code}.")
    return response


def upload_resume(path: str, data: bytes) -> None:
    bucket = get_settings().resume_bucket
    content_type = _CONTENT_TYPES.get(PurePosixPath(path).suffix, "application/octet-stream")
    _request(
        "POST",
        f"{_base()}/object/{bucket}/{path}",
        # Same content always maps to the same path, so overwriting is a no-op.
        extra_headers={"Content-Type": content_type, "x-upsert": "true"},
        content=data,
    )


def signed_resume_url(path: str) -> str:
    settings = get_settings()
    response = _request(
        "POST",
        f"{_base()}/object/sign/{settings.resume_bucket}/{path}",
        json={"expiresIn": settings.signed_url_ttl_seconds},
    )
    signed = response.json().get("signedURL") or response.json().get("signedUrl")
    if not signed:
        raise HTTPException(status_code=502, detail="Supabase Storage returned no signed URL.")
    return signed if signed.startswith("http") else f"{_base()}{signed}"
