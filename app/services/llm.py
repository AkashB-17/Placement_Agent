from typing import TypeVar

from fastapi import HTTPException
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)

EXTRACT_PREAMBLE = (
    "Extract only facts that appear in the source document. "
    "If a field is not explicitly stated, use null for optional scalars and [] for lists. "
    "Never invent, guess, or fill in missing values."
)


def extract_structured(text: str, schema: type[T], instructions: str) -> T:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    client = OpenAI(api_key=settings.openai_api_key)
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
    except HTTPException:
        raise
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"LLM output failed schema validation: {exc.errors()}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"LLM extraction failed: {exc}",
        ) from exc
