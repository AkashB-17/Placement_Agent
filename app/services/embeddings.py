from openai import OpenAIError

from app.config import get_settings
from app.services.llm import get_openai_client, openai_error_to_http


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    client = get_openai_client()
    try:
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=texts,
        )
    except OpenAIError as exc:
        raise openai_error_to_http(exc) from exc
    return [item.embedding for item in sorted(response.data, key=lambda row: row.index)]
