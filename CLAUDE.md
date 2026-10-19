# Campus Placement Agent: context for Claude sessions

## Project
Placement officer uploads a job description; eligible students are scored against it from their resumes, with matched/missing skills and evidence. Portfolio/academic project that must be defended to evaluators, so prefer defensible engineering over buzzwords. Owner: Akash (final-year B.Tech CS, strong in Python/FastAPI/GenAI, new to Supabase/Next.js — explain those basics when they come up). Give frank tradeoffs, keep explanations short.

## Design decisions (do not relitigate without a strong reason)
1. Eligibility (CGPA, active backlogs, branch, batch, placed-student rule) is deterministic Python, never an LLM or similarity search. Only eligible students are scored.
2. The score is computed in code from skill coverage. The LLM only returns per-skill evidence with a resume quote; code checks the quote really appears in the resume and downgrades it otherwise. Every score ships with matched/missing skills and evidence. Scoring uses the full resume text (resumes are short; top-k retrieval risked missing skills).
3. RAG ingests policy/JD/resume text; it is used to cite the policy (or JD) clause behind each eligibility failure. RAG never decides eligibility.
4. Auto-apply (not built yet) must be staged: pending application → notify student → release after the 24h withdraw window or at deadline-minus-buffer. Opt-in with preferences; pins a resume version; never rewrites resumes. Currently only `auto_apply_recommended = eligible AND score >= threshold` (config `auto_apply_threshold`, default 80).
5. Honest framing: the JD → parse → filter → score → threshold pipeline is a deterministic workflow with LLM steps, not a truly agentic system. Don't oversell it in docs.
6. Milestone-1 stack: FastAPI + ChromaDB + SQLite + OpenAI only (gpt-4o-mini, text-embedding-3-small). No Gemini/Groq.
7. Later: Next.js (auth + UI) talks to hosted Supabase (Postgres + Auth + private Storage, RLS). FastAPI verifies the Supabase JWT via JWKS and uses the secret key server-side, so every endpoint needs an explicit `require_role` check. Roles in a profiles table or app_metadata, never user_metadata. Privileged roles by invitation only. No Docker / local Supabase.
8. Resume PDFs never live in SQLite or on the laptop long-term; later a private Supabase Storage bucket, parsed JSON in Postgres.
9. No heavy dependencies until a feature needs them (no sentence-transformers/PyTorch, spaCy, LangGraph, pandas, LangChain chains). Use chromadb and openai SDKs directly; langchain-text-splitters only for chunking.

## Repo layout
Python 3.12, uv-managed (`uv sync --group dev`, `uv run pytest`, `uv run uvicorn app.main:app --reload`).
- `app/main.py` FastAPI app, lifespan `init_db`, `/health`, routers
- `app/config.py` pydantic-settings (`get_settings`/`set_settings`/`reset_settings`), `.env` at repo root
- `app/db.py` sqlite3 tables `policies`, `jds`, `students`; upsert/get/list helpers; `make_document_id` = sha256 prefix of content
- `app/schemas.py` Pydantic models (PolicyRules, JDRequirements, ParsedResume, StudentProfile, responses)
- `app/services/llm.py` `extract_structured` (OpenAI structured outputs); OpenAI errors → 502, schema failures → 422
- `app/services/embeddings.py`, `vectorstore.py` (Chroma collections policies/jds/resumes, cosine; idempotent ingest: embed, then delete-by-doc_id, then upsert), `chunking.py`, `pdf.py`
- `app/services/normalize.py` deterministic branch/batch normalization (CSE, ECE, …; "2027")
- `app/services/eligibility.py`, `scoring.py`, `app/routers/match.py` (`POST /match`, `GET /jds/{id}/ranked`)
- `tests/` LLM and embeddings are always mocked (conftest patches `app.services.vectorstore.embed_texts`, uses tmp_path for SQLite and Chroma). No live OpenAI calls in tests.
- `data/sample/` committed demo data; `data/*.db`, `.chroma/`, `.env` ignored.

## Working rules
- Never print, log or commit secrets (OpenAI key, Supabase secret key, JWKS contents). `.env` stays out of git.
- Don't add dependencies, frameworks or infrastructure the current task doesn't need; ask before adding any dependency.
- Run `uv run pytest` before declaring anything done; report honestly what was and wasn't verified.
- If a command fails, report the exact error; don't loop on the same failure more than a couple of times.
- Commit messages in imperative mood, small commits, no secrets.
