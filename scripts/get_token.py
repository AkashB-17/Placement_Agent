"""
Log in to Supabase with email + password and print an access token for /docs.

    uv run python scripts/get_token.py --email you@example.com

The password is typed at a hidden prompt and sent only to your Supabase project.
Paste the printed token into the "Authorize" button at http://127.0.0.1:8000/docs,
or pass it to scripts/seed_sample.py with --token. Tokens expire after about an hour.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Print a Supabase access token.")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_publishable_key):
        print("Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY in .env first.", file=sys.stderr)
        return 1

    password = getpass.getpass("Supabase password: ")
    response = httpx.post(
        f"{settings.supabase_url.rstrip('/')}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": settings.supabase_publishable_key},
        json={"email": args.email, "password": password},
        timeout=30,
    )
    if response.status_code != 200:
        message = response.json().get("error_description") or response.json().get("msg") or response.text
        print(f"Login failed ({response.status_code}): {message}", file=sys.stderr)
        return 1
    print(response.json()["access_token"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
