from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, reset_settings, set_settings
from app.db import init_db
from app.services.vectorstore import reset_clients


def fake_embed_texts(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        seed = float(len(text) % 10) / 10.0
        vectors.append([seed, 1.0 - seed, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    return vectors


@pytest.fixture
def client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    set_settings(
        Settings(
            openai_api_key="test-key",
            sqlite_path=tmp_path / "test.db",
            chroma_path=tmp_path / "chroma",
        )
    )
    reset_clients()
    init_db()
    monkeypatch.setattr("app.services.vectorstore.embed_texts", fake_embed_texts)

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    reset_clients()
    reset_settings()
