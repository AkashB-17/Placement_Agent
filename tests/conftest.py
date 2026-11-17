from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user, reset_jwks_clients
from app.config import Settings, reset_settings, set_settings
from app.db import init_db
from app.services.vectorstore import reset_clients

ADMIN = CurrentUser(id="00000000-0000-0000-0000-00000000000a", email="admin@test.local", role="admin")


def fake_embed_texts(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        seed = float(len(text) % 10) / 10.0
        vectors.append([seed, 1.0 - seed, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    return vectors


def make_test_settings(tmp_path, **overrides) -> Settings:
    """Never read .env: it may point at the real Supabase project."""
    values = dict(
        openai_api_key="test-key",
        sqlite_path=tmp_path / "test.db",
        chroma_path=tmp_path / "chroma",
        database_url="",
        supabase_url="",
        supabase_publishable_key="",
        supabase_secret_key="",
        dev_auth_bypass=False,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def app_and_user(tmp_path, monkeypatch):
    set_settings(make_test_settings(tmp_path))
    reset_clients()
    reset_jwks_clients()
    init_db()
    monkeypatch.setattr("app.services.vectorstore.embed_texts", fake_embed_texts)

    from app.main import app

    current = {"user": ADMIN}
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    yield app, current
    app.dependency_overrides.clear()
    reset_clients()
    reset_jwks_clients()
    reset_settings()


@pytest.fixture
def client(app_and_user) -> Generator[TestClient, None, None]:
    """Signed in as an admin unless a test calls `login_as`."""
    app, _ = app_and_user
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def login_as(app_and_user) -> Callable[..., CurrentUser]:
    _, current = app_and_user

    def _login(role: str, email: str | None = None, user_id: str | None = None) -> CurrentUser:
        current["user"] = CurrentUser(
            id=user_id or f"00000000-0000-0000-0000-{abs(hash((role, email))) % 10**12:012d}",
            email=email,
            role=role,
        )
        return current["user"]

    return _login
