from typing import TypeVar

from fastapi import HTTPException
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)

EXTRACT_PREAMBLE = (
    "Extract only facts that appear in the source document. "
    "If a field is not explicitly stated, use null for optional scalars and [] for lists. "
    "Never invent, guess, or fill in missing values."
)


def get_openai_client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")
    return OpenAI(api_key=settings.openai_api_key)


def openai_error_to_http(exc: OpenAIError) -> HTTPException:
    """Map an upstream OpenAI failure to a 502 with a short, key-free message."""
    if isinstance(exc, AuthenticationError):
        detail = "OpenAI authentication failed."
    elif isinstance(exc, RateLimitError):
        detail = "OpenAI rate limit exceeded."
    elif isinstance(exc, APIConnectionError):
        detail = "Could not connect to OpenAI."
    elif isinstance(exc, APIStatusError):
        detail = f"OpenAI API error {exc.status_code}."
    else:
        detail = f"OpenAI request failed: {type(exc).__name__}."
    return HTTPException(status_code=502, detail=detail)


def extract_structured(text: str, schema: type[T], instructions: str) -> T:
    settings = get_settings()
    client = get_openai_client()
    try:
        completion = client.chat.completions.parse(
            model=settings.openai_chat_model,
            messages=[
                {"role": "system", "content": f"{EXTRACT_PREAMBLE} {instructions}"},
                {"role": "user", "content": text},
            ],
            response_format=schema,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise HTTPException(
                status_code=422,
                detail="LLM returned no structured output for the given schema.",
            )
        return schema.model_validate(parsed)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"LLM output failed schema validation: {exc.errors(include_input=False)}",
        ) from exc
    except OpenAIError as exc:
        raise openai_error_to_http(exc) from exc
