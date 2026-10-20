# Campus Placement Agent

Backend for a campus placement system. A placement officer uploads a placement policy and a job description; students are checked for eligibility and scored against the JD from their resumes. The officer gets a ranked list with matched/missing skills, the resume evidence behind each match, and, for ineligible students, the exact rule they failed plus the policy or JD clause it comes from.

**Honest framing:** the pipeline (parse JD → filter → score → threshold) is a deterministic workflow with LLM steps, not an autonomous agent. Auto-apply is only a recommendation flag at this stage.

## How it decides

| Step | Who decides | Notes |
|---|---|---|
| Parse policy / JD / resume | LLM (gpt-4o-mini, structured outputs) | Validated against Pydantic schemas; branches and batches are then normalized in code (`CSE`, `2027`) |
| Eligibility | Plain Python | CGPA (stricter of policy and JD), active backlogs, branch, batch, placed-student rule. Every failure is reported. Unstated rules are not enforced |
| Skill evidence | LLM | Per JD skill: evidenced yes/no plus a verbatim resume quote |
| Evidence check | Code | Quote must appear in the resume and mention the skill; skills the LLM omits count as missing |
| Score | Code | `100 × (0.75 × required coverage + 0.25 × preferred coverage)`; no preferred skills → required only; no required skills → `null` |
| Citations | RAG (ChromaDB) | For each failed rule, the top-2 chunks from the policy or JD the rule came from |
| Auto-apply | Code | `auto_apply_recommended = eligible AND score ≥ AUTO_APPLY_THRESHOLD` (default 80). Nothing is applied |

Known limits: the "quote mentions the skill" check is a token heuristic and can reject paraphrased evidence (it errs toward under-scoring). `/ranked` makes one LLM call per eligible student on every request; results aren't cached yet.

## Setup

Python 3.12, managed with `uv`.

```bash
uv sync --group dev
```

Create `.env` in the project root (never commit it):

```
OPENAI_API_KEY=sk-...
OPENAI_CHAT_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
SQLITE_PATH=./data/placement.db
CHROMA_PATH=./.chroma
AUTO_APPLY_THRESHOLD=80
```

## Run

```bash
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs.

| Endpoint | Purpose |
|---|---|
| `POST /policies`, `POST /jds` | Form field `text` **or** a `.pdf`/`.txt` `file` (not both) |
| `POST /students` | Form fields `name`, `branch`, `batch`, `cgpa` (0–10), `active_backlogs`, `is_placed`, plus a `.pdf`/`.txt` `resume` |
| `GET /policies`, `/jds`, `/students` and `GET /{resource}/{id}` | Discover ids, inspect extracted JSON |
| `POST /match` | `{jd_id, student_id, policy_id}` → eligibility, score breakdown, citations |
| `GET /jds/{jd_id}/ranked?policy_id=...` | Eligible students by score, then ineligible students with failed rules and citations |

Error codes: `400` nothing supplied, `404` unknown id, `415` unsupported file type, `422` bad input or unparseable file, `502` OpenAI unavailable.

Demo flow: ingest one policy, a JD and ~10 students from `data/sample/`, then call `/jds/{id}/ranked`.

## Tests

LLM and embedding calls are mocked; tests make no OpenAI requests.

```bash
uv run pytest
```

## Roadmap

Hosted Supabase (Postgres, Auth with roles, private Storage for resumes, RLS) → Next.js frontend → staged auto-apply with a 24h withdraw window → student-side agent (drive watcher, resume-gap nudges).
