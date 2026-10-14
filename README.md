# Campus Placement Agent

Backend for an agentic campus placement system. It ingests placement policies, job descriptions, and student resumes, extracts structured JSON with the OpenAI API, stores records in SQLite, and embeds chunks in ChromaDB.

This stage covers ingestion only. Matching and eligibility are not implemented yet.

## Setup

Python 3.12. Dependencies are managed with `uv`.

```bash
uv sync --group dev
```

Create a `.env` in the project root (do not commit it):

```
OPENAI_API_KEY=sk-...
OPENAI_CHAT_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
SQLITE_PATH=./data/placement.db
CHROMA_PATH=./.chroma
```

## Run

```bash
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs and POST a sample policy, JD, and student resume.

- `POST /policies` — form field `text` and/or upload `file`
- `POST /jds` — form field `text` and/or upload `file`
- `POST /students` — form fields `name`, `branch`, `batch`, `cgpa`, `active_backlogs` plus a resume PDF (`resume`)

SQLite is written to `SQLITE_PATH`. Vectors live in `CHROMA_PATH` under collections `policies`, `jds`, and `resumes`. Re-posting the same policy text upserts the same document id and does not grow the vector count.

## Tests

LLM and embedding API calls are mocked. No live OpenAI requests are made.

```bash
uv run pytest
```
