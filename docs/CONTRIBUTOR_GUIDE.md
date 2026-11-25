# Contributor Guide

Everything you need to find your way around the code, run it, change it safely and ship it. For what the product does from a user's point of view, read [PRODUCT_GUIDE.md](PRODUCT_GUIDE.md) first.

**Contents**
1. [Principles you must not break](#1-principles-you-must-not-break)
2. [Architecture](#2-architecture)
3. [Three request flows, end to end](#3-three-request-flows-end-to-end)
4. [Repository map](#4-repository-map)
5. [Running it locally](#5-running-it-locally)
6. [Backend reference, file by file](#6-backend-reference-file-by-file)
7. [Data model](#7-data-model)
8. [API reference](#8-api-reference)
9. [Frontend reference](#9-frontend-reference)
10. [Scripts](#10-scripts)
11. [Tests](#11-tests)
12. [Recipes for common changes](#12-recipes-for-common-changes)
13. [Deployment and operations](#13-deployment-and-operations)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Principles you must not break

These are design decisions, not accidents. A change that breaks one needs a strong, written reason.

| # | Principle | Where it is enforced |
|---|---|---|
| 1 | **Eligibility is plain Python**, never an LLM or a similarity search. Only eligible students are scored. | `app/services/eligibility.py` |
| 2 | **The score is computed in code** from skill coverage. The LLM only returns per-skill evidence with a quote; code verifies each quote against the resume. Every score ships with matched/missing skills and evidence. | `app/services/scoring.py` |
| 3 | **Retrieval (RAG) only cites**, never decides. It finds the policy/JD clause behind a failed rule. | `app/services/matching.py` (`_cite`), `vectorstore.py` |
| 4 | **Auto-apply is staged**: pending → notify → withdraw window → submitted. Auto-apply never re-applies after a withdrawal (the student may, manually). Applications pin the resume version and score snapshot. Resumes are never rewritten. | `app/services/auto_apply.py`, `db.release_due_applications` |
| 5 | **Every endpoint has an explicit role check** (`require_role`). The API uses the Supabase *secret* key, which bypasses RLS, so RLS is defence in depth, not the main guard. | `app/auth.py`, every router |
| 6 | **Roles live in `public.profiles`**, never in `user_metadata` or token claims. Sign-up always creates a `student`. | migration `20261105000000_init.sql`, `auth.get_current_user` |
| 7 | **Secrets never reach the browser, logs or git.** `.env` is git-ignored; the web app only holds `NEXT_PUBLIC_` (browser-safe) values. | `.gitignore`, `web/.env.local.example` |
| 8 | **Resume files never live on local disk or in SQLite long-term**: private Supabase Storage bucket, content-addressed paths, 60 s signed URLs. | `app/services/storage.py` |
| 9 | **No heavy dependencies** until a feature needs them (no LangChain chains, LangGraph, PyTorch, spaCy, pandas). Use the `openai` and `chromadb` SDKs directly. Ask before adding any dependency. | `pyproject.toml` |
| 10 | **Honest framing.** This is a deterministic workflow with LLM steps, not an autonomous agent. Keep docs and UI copy honest. | everywhere |

---

## 2. Architecture

```
                       ┌───────────────────────────── Supabase ─────────────────────────────┐
                       │  Auth (JWT, ES256)   Postgres (+RLS)   Storage: private "resumes"  │
                       └──────▲──────────────────────▲──────────────────────▲───────────────┘
                     sign in  │                      │ SQL (psycopg pool)   │ REST (secret key)
                              │                      │                      │
  Browser ── Next.js app (web/, Vercel) ──bearer JWT──▶ FastAPI (app/, Render) ──▶ OpenAI
            client-rendered, Tailwind                 │   gpt-4o-mini: extraction + evidence
                                                      │   text-embedding-3-small: citations
                                                      └──▶ ChromaDB (local disk, derived index)
```

- **The web app talks to Supabase only to sign in.** All data goes through FastAPI with the user's access token.
- **FastAPI is the only writer.** It verifies the JWT against Supabase's public keys (JWKS), reads the role from `profiles`, checks it, then reads/writes Postgres and Storage with server credentials.
- **Postgres is the source of truth.** Chroma is a *derived* index of policy/JD text used only for citations; it is rebuilt from Postgres when missing (`index_sync.py`).
- **Two database backends, one API.** With `DATABASE_URL` set, the app uses Postgres (Supabase). Without it, it uses a local SQLite file, which is how tests and the offline demo run. `app/db.py` hides the difference.

---

## 3. Three request flows, end to end

### 3.1 Uploading a JD (`POST /jds`)
1. `routers/jds.py::create_jd` checks the role (officer, admin, recruiter).
2. `services/pdf.py::resolve_source_text` takes *either* pasted text *or* a `.pdf/.txt` file (both → 422, unsupported type → 415) and normalises line endings.
3. `services/llm.py::extract_structured` asks gpt-4o-mini (temperature 0, structured outputs) for a `JDRequirements` object.
4. `services/normalize.py::normalize_branches` / `normalize_batch` turn branch and batch text into codes ("Computer Science & Engg." → `CSE`, "CSE/IT" → `CSE, IT`, "all branches" → no rule, "2023-27" → `2027`).
5. `services/grounding.py::ground_jd` drops a batch or CGPA rule the source text does not actually state and returns a warning.
6. `db.upsert_jd` stores it under `make_document_id(text)` (a content hash, so re-uploading the same text updates, not duplicates). A recruiter cannot overwrite another user's JD (403).
7. `services/vectorstore.py::ingest_document` chunks the text by clause (400 chars), embeds it, and indexes it for citations.

### 3.2 Ranking students for a JD (`GET /jds/{id}/ranked?policy_id=`)
1. `routers/match.py::ranked` (staff only) loads the policy and JD (`services/matching.py::load_policy/load_jd`).
2. `matching.py::evaluate_many` evaluates all students in parallel (8 threads). For each, `evaluate_student`:
   - runs `eligibility.py::check_eligibility` (always fresh, never cached);
   - if **ineligible**: `_cite` retrieves the clause behind each failed rule from the source document;
   - if **eligible**: `scoring.py::score_student_cached` returns the stored score or calls `score_student` (one LLM call) and stores it.
3. Results are sorted (score desc, unscored last, name), with counts of fresh AI calls vs cache hits.

### 3.3 Auto-apply (`POST /jds/{id}/auto-apply?policy_id=`)
1. `routers/applications.py::run_auto_apply` (staff only) calls `services/auto_apply.py::run_auto_apply`.
2. It first runs `release_due()`, so statuses and counts are current.
3. Deadline: `parse_deadline` reads the JD's deadline text deterministically; `release_time` computes `release_at = min(now + 24 h, deadline − 6 h)`. Deadline passed, or less than 60 min left to withdraw → 409.
4. For each opted-in student (`db.list_opted_in_students`), cheap checks first: already applied (any status), excluded company, policy application limit. Survivors go through `evaluate_many`. Not eligible, no score, or score below `max(threshold, student's min_score)` → skipped *with a reason*.
5. Qualifiers: `db.create_application` inserts the pending application **and** its notification in one transaction (`_atomic`). `ON CONFLICT (student_id, jd_id) DO NOTHING` prevents double-applying.
6. Later, `db.release_due_applications` (one conditional `UPDATE … WHERE status='pending' AND release_at <= now`) moves due rows to `submitted` and notifies. It runs every 60 s (`main._release_sweep`) **and** before every read of applications.

---

## 4. Repository map

```
app/                      FastAPI backend
  main.py                 app, lifespan, middleware, /health, routers
  config.py               settings (pydantic-settings, .env)
  auth.py                 JWT verification, roles, require_role
  db.py                   all SQL, Postgres + SQLite
  schemas.py              Pydantic models (API contract)
  routers/                HTTP endpoints, one file per area
  services/               business logic, no HTTP
supabase/
  migrations/             Postgres schema, RLS, storage policies (source of truth)
  config.toml             Supabase CLI link config
web/                      Next.js 16 + Tailwind 4 front end
  app/                    pages (App Router), one folder per route
  components/             shared UI
  lib/                    API client, auth context, types, data hooks
scripts/                  CLI tools: tokens, seeding, data import, PDF generation
tests/                    pytest suite (LLM/embeddings/Supabase always mocked)
data/sample/              committed demo data + answer key
data/generated/           committed fictional dataset (Gemini) + answer keys
data/real_jds/            real company JDs, git-ignored
docs/                     these guides
render.yaml               Render Blueprint for the API
.env.example              every setting the API reads (names only)
```

---

## 5. Running it locally

**Prerequisites:** Python 3.12, [uv](https://docs.astral.sh/uv/), Node 20.9+ (for `web/`).

```bash
uv sync --group dev
cp .env.example .env            # then fill it in
uv run pytest                   # ~230 tests, all offline
```

**Mode A: offline (no Supabase).** In `.env` set only `OPENAI_API_KEY` and `DEV_AUTH_BYPASS=true`, and leave `DATABASE_URL` empty. Every request acts as an admin, data lives in `data/placement.db` (SQLite), and resume files are not stored (text only). The bypass is refused at startup if `DATABASE_URL` is set.

```bash
uv run uvicorn app.main:app --reload --port 8000     # API docs at http://127.0.0.1:8000/docs
uv run python scripts/seed_sample.py                  # load data/sample and check against the answer key
```

**Mode B: with Supabase** (real auth, Postgres, Storage). Fill `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `DATABASE_URL` (Session pooler URI). Apply migrations with the Supabase CLI (`npx supabase@latest db push --linked`). Then:

```bash
uv run uvicorn app.main:app --port 8000
cp web/.env.local.example web/.env.local      # URL + publishable key + API URL
npm --prefix web install
npm --prefix web run dev                       # http://localhost:3000
```

Get a token for scripts or `/docs` → *Authorize* with `uv run python scripts/get_token.py --email you@example.com` (the password is typed at a hidden prompt).

---

## 6. Backend reference, file by file

### 6.1 Core

#### `app/main.py`: application entry point
| Name | What it does |
|---|---|
| `check_startup_settings()` | Refuses to start if `DEV_AUTH_BYPASS` is on with Postgres. |
| `lifespan(app)` | Startup: `open_pool()` → `init_db()` → starts the release sweep task and the background vector-index sync. Shutdown: cancels the sweep, closes the pool. |
| `_release_sweep(interval)` | Every `RELEASE_SWEEP_SECONDS` (60), runs `auto_apply.release_due_quietly` in a thread. |
| `UnhandledErrorMiddleware` | Turns an unexpected exception into a JSON 500 *inside* the CORS layer, so the browser sees a real error instead of a CORS failure. Logs the traceback; returns no internals. |
| `SettingsCORSMiddleware` | CORS for the web app. Reads `CORS_ORIGINS` when the middleware is first built (not at import, so tests never read `.env`). Bearer tokens, no cookies, so credentials are off. |
| `health()` | `GET /health` → `{"status": "ok"}` (used by Render's health check). |

Middleware order matters: the last added runs first, so CORS wraps the error handler.

#### `app/config.py`: settings
- `Settings` (pydantic-settings) reads `.env` at the repo root. Groups: OpenAI models; local paths (`sqlite_path`, `chroma_path`); `auto_apply_threshold` (80); auto-apply timing (`auto_apply_withdraw_hours` 24, `auto_apply_deadline_buffer_hours` 6, `auto_apply_min_window_minutes` 60, `deadline_utc_offset_minutes` 330 = IST, `release_sweep_seconds` 60); `index_sync_on_startup`; Supabase (`supabase_url`, keys, `database_url`, `resume_bucket`, `signed_url_ttl_seconds` 60); `dev_auth_bypass`; `cors_origins` (a JSON list in `.env`).
- `_project_url_only` validator strips `/rest/v1`, `/auth/v1`, `/storage/v1` from `SUPABASE_URL`, so the dashboard's Data API URL also works.
- `get_settings()` / `set_settings()` / `reset_settings()`: a process-wide singleton; tests swap it with `set_settings`.

#### `app/auth.py`: authentication and roles
| Name | What it does |
|---|---|
| `CurrentUser(id, email, role)` | The authenticated user passed to endpoints. |
| `ROLES`, `STAFF` | All roles; staff = officer + admin. |
| `get_jwks_client()` / `reset_jwks_clients()` | Cached `PyJWKClient` for `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. |
| `verify_token(token)` | Verifies the signature (ES256/RS256 only), `aud="authenticated"`, `iss=<url>/auth/v1`, and that `exp/sub/aud/iss` exist. Expired → 401 "Token expired."; anything else → 401 "Invalid token."; JWKS unreachable → 503. |
| `get_current_user()` | Dev bypass → admin. No token → 401. Verified token → role from `db.get_profile_cached(sub)`; no profile → 403. Email comes from the token (Supabase-verified). |
| `require_role(*roles)` | FastAPI dependency factory: 403 unless the user's role is listed. |
| `any_user`, `staff_only` | Shortcuts for all roles and officer/admin. |

#### `app/db.py`: all persistence
One set of functions over two backends. Write queries once with `?` placeholders; `_sql()` rewrites them to `%s` for psycopg. JSON columns are `jsonb` in Postgres and text in SQLite.

| Area | Functions | Notes |
|---|---|---|
| Plumbing | `using_postgres`, `get_connection` (SQLite), `_get_pool`, `open_pool`, `close_pool`, `_transaction`, `_atomic`, `_sql`, `_execute`, `_fetchall`, `_fetchone`, `_json_param`, `_json_value` | Postgres: `psycopg_pool` (max 5, **autocommit**, every helper call is one statement). A connection is pinged only if idle > 30 s (`_check_if_idle`). Unreachable DB → 503, and the connection string is never echoed. `_atomic()` is for several statements that must commit together. |
| Schema | `SQLITE_SCHEMA`, `_SQLITE_ADDED_COLUMNS`, `init_db` | SQLite: creates tables and adds missing columns. Postgres: only *checks* that the migrated tables exist (profiles, applications, score_cache) and fails fast with the migration to apply. |
| Ids | `make_document_id(*parts)` | sha256 prefix of the content: same text → same id → upsert, not duplicate. |
| Profiles | `get_profile`, `get_profile_cached`, `clear_profile_cache`, `list_profiles`, `set_profile_role`, `upsert_profile` | Auth reads roles through a 60 s cache (Postgres only); `set_profile_role` clears it. `upsert_profile` is for SQLite/tests (Supabase creates profiles with a trigger). |
| Documents | `upsert_policy`, `upsert_jd`, `list_policies`, `get_policy`, `list_jds`, `get_jd`, `list_policy_sources`, `list_jd_sources` | `created_by` keeps the original creator (`COALESCE`). The `*_sources` functions feed the index rebuild. |
| Students | `upsert_student_record`, `set_student_resume`, `find_student_id`, `list_students`, `get_student`, `get_student_by_email`, `get_all_students`, `_student` | The office owns the academic record (`upsert_student_record` never touches CV columns); the student owns the CV (`set_student_resume`). `find_student_id` reuses an existing record (by email, else name+branch+batch) so ids are stable and a new CV never creates a new student. `get_student_by_email` is case-insensitive. |
| Timestamps | `_ts`, `_dt`, `_bool` | `timestamptz` in Postgres, UTC ISO text in SQLite (sorts correctly as text). |
| Auto-apply | `get_preferences`, `upsert_preferences`, `list_opted_in_students`, `application_statuses_for_jd`, `active_application_counts`, `create_application`, `release_due_applications`, `withdraw_application`, `get_application`, `list_applications`, `_application` | `create_application`, `release_due_applications` and `withdraw_application` each write the state change **and** its notification atomically. Release and withdraw are single conditional `UPDATE`s, so they cannot both win a race. |
| Notifications | `_insert_notification`, `list_notifications`, `mark_notifications_read` | In-app only. |
| Score cache | `get_cached_score`, `put_cached_score`, `count_cached_scores` | Keyed by `scoring.score_cache_key`. |

#### `app/schemas.py`: the API contract
Pydantic models, mirrored by hand in `web/lib/types.ts` (keep them in sync).
- **Extraction targets:** `PolicyRules`, `JDRequirements`, `ParsedResume`.
- **Students:** `StudentProfile`, `StudentSummary`, `StudentDetail`, `ResumeLink`.
- **Ingest responses:** `PolicyIngestResponse`, `JDIngestResponse`, `StudentIngestResponse` (with `warnings`).
- **Lists/details:** `PolicySummary`, `PolicyDetail`, `JDSummary`, `JDDetail`.
- **Admin:** `Role`, `InviteRequest`, `RoleUpdate`, `ProfileOut`.
- **Matching:** `FailedRule`, `EligibilityResult`, `SkillQuote`, `ScoreBreakdown`, `CitationChunk`, `Citation`, `MatchRequest`, `MatchResult` (incl. `score_source`: cache/fresh/none), `RankedResponse` (incl. `ai_calls`, `cached_scores`).
- **Auto-apply:** `ApplicationStatus`, `AutoApplyPreferences`, `PreferencesOut`, `ApplicationOut`, `SkippedStudent`, `AutoApplyRun`, `NotificationOut`.

### 6.2 Routers (`app/routers/`)
Routers are thin: role check → validate → call services/db → shape the response. Full route list in [§8](#8-api-reference).

| File | Responsibility | Notable helpers |
|---|---|---|
| `policies.py` | Upload/list/read placement policies. | `POLICY_INSTRUCTIONS` (extraction prompt), `_creator` |
| `jds.py` | Upload/list/read JDs; recruiter ownership check. | `JD_INSTRUCTIONS` (extraction prompt) |
| `students.py` | Office adds/updates academic records (CV optional; email required without one); students upload/replace their own CV (`PUT /students/me/resume`); list, read, own record, CV link. | `RESUME_INSTRUCTIONS`, `_detail`, `_prepare_cv` (read, parse, store; runs before any DB write), `_set_cv`, `owns_student_record` (email match) |
| `match.py` | `POST /match` (one student) and `GET /jds/{id}/ranked` (all students). | uses `services/matching.py` |
| `applications.py` | Auto-apply: student preferences, applications, withdraw, notifications; officer run; staff/recruiter list; pinned-resume link. | `_my_student`, `_preferences_out` |
| `admin.py` | List users, invite with a role, change a role (an admin can't demote themselves), `/admin/me`. | |

### 6.3 Services (`app/services/`): the business logic

#### `eligibility.py`: deterministic rules
- `RULE_DESCRIPTIONS`: natural-language description per rule (shown to users, and used as the citation search query).
- `check_eligibility(student, policy, jd) -> EligibilityResult`: CGPA (stricter of policy and JD override, attributed to whichever is stricter), active backlogs (policy), branch and batch (policy *and* JD, each reported separately), placed-student rule (only if the policy says placed students cannot apply). **All** failures are returned.
- `_membership_failures(...)`: branch/batch check. It re-normalises stored allowed lists, so rows saved before a normalisation fix still compare correctly; an allowed list that normalises to empty means "no restriction".
- `_fail(...)`: builds a `FailedRule`.

#### `normalize.py`: branch and batch normalisation
- `_BRANCH_ALIASES`: lowercase alias → code (CSE, ECE, EEE, EE, ME, CE, IT, AI-ML, DS). Add aliases here.
- `normalize_branch(value)`: one value → code; unknown values are upper-cased unchanged.
- `expand_branches(value)`: one entry → codes, splitting compounds ("B.Tech CSE/IT/ECE" → CSE, IT, ECE) only if **every** part is known; a known name such as "AI/ML" is never split.
- `normalize_branches(values)`: list version. Any "all/any branches/streams" entry → `[]` (no rule); "circuit branches" → `CIRCUIT_BRANCHES`.
- `is_unrestricted(value)`, `CIRCUIT_BRANCHES`.
- `normalize_batch(value)`: → 4-digit graduation year ("2023-27" → 2027, "Class of 2027" → 2027).
- `normalize_list(values, fn)`: normalise, drop empties, de-duplicate in order.

#### `grounding.py`: guard against invented rules
- `ground_policy(rules, text)` / `ground_jd(requirements, text)`: mutate in place, return warnings.
- `_ground_batches`: a batch year must appear in a sentence about batches/graduation (so a 2026 *deadline* isn't read as "batch 2026").
- `_ground_cgpa`: the CGPA number must appear in the text (`_number_in_text`, which doesn't match "7" inside "7.5").
- Branches and backlog limits are not grounded yet.

#### `scoring.py`: evidence-based score
| Name | What it does |
|---|---|
| `SkillEvidence`, `EvidenceReport` | The LLM's answer shape: per skill, `evidenced` + `evidence_quote`. |
| `_evidence_instructions(skills)` | The evidence prompt (includes the JD's skill list). |
| `quote_in_resume(quote, resume)` | The quote must appear verbatim, tolerant of case, whitespace and edge punctuation. A quote glued from several sentences (or joined with "...") must have each fragment present, in order. |
| `quote_mentions_skill(quote, skill)` | Token heuristic (stopwords ignored): the quote must mention the skill. |
| `validate_evidence(item, resume)` | Applies both checks; returns a `SkillQuote` or `None`. |
| `compute_score(required_coverage, preferred_coverage)` | `100 × (0.75·required + 0.25·preferred)`; no preferred skills → required only; no required skills → `None`. |
| `_dedupe` | De-duplicates skills; preferred skills that are also required are dropped from preferred. |
| `score_student(student, jd)` | One LLM call on the **full** resume text, then validation. Skills the LLM omits count as missing. |
| `SCORING_VERSION`, `score_cache_key(resume_text, jd)` | Cache key = sha256 of (version, model, evidence prompt incl. skill lists, resume sha256). |
| `score_student_cached(student, jd, jd_id, refresh)` | Cache read/write around `score_student`; returns `(breakdown, "cache" | "fresh" | "none")`. |

#### `matching.py`: shared evaluation (used by `/match`, `/ranked`, auto-apply)
- `load_policy`, `load_jd`, `load_student`: load or 404.
- `_cite(rule, policy_id, jd_id)`: retrieves the top `CITATION_K` (2) chunks from the document the rule came from.
- `evaluate_student(...) -> MatchResult`: eligibility → citations (ineligible) or cached score (eligible) → `auto_apply_recommended = score ≥ threshold`.
- `evaluate_many(...)`: the same in parallel (`RANK_WORKERS` = 8 threads), results in input order.

#### `auto_apply.py`: staged auto-apply
| Name | What it does |
|---|---|
| `utcnow()` | The clock; tests monkeypatch it to move time. |
| `local_zone()` | Fixed UTC offset from `deadline_utc_offset_minutes` (no tz database needed, which matters on Windows). |
| `parse_deadline(text)` | Deterministic: ISO, "November 20, 2026", "20th Nov 2026", "Friday, 4 December 2026", "20/11/2026" (day first), "30-11-2026". A date means 23:59:59 local. Unrecognised → `None`. |
| `release_time(now, deadline)` | `(release_at, cutoff)` = (min(now + window, deadline − buffer), deadline − buffer). |
| `format_local`, `_job_label` | Message formatting. |
| `release_due()`, `release_due_quietly()` | Run the release `UPDATE`; the quiet version logs instead of raising (for the background sweep). |
| `to_out(application, now)` | DB row → `ApplicationOut` (computes `can_withdraw`; `source` is `manual` when the creator's profile role is `student`, else `auto`). |
| `application_window(jd, now)` | `(deadline, release_at, cutoff)` or 409 (deadline passed / too little time to withdraw). Shared by runs and manual applies. |
| `apply_manually(student, jd_id, policy_id, actor_id)` | A student applies from the job board: already pending/submitted → 409 (withdrawn → re-apply: `db.reapply_application` flips the same row back to pending with a fresh snapshot and window) → window → CV present → policy limit → `check_eligibility` (before any AI call) → score snapshot → same pending application + notification. No score bar or excluded-companies check: the student chose the job. |
| `run_auto_apply(jd_id, policy_id, actor_id)` | The whole run (see [§3.3](#33-auto-apply-post-jdsidauto-applypolicy_id)); returns created + skipped-with-reason + not-opted-in count. |

#### `highlights.py`: "why they stand out"
`build_highlights(student, policy, jd, breakdown)` returns short factual lines: required-skill coverage (from the verified breakdown), matched preferred skills, CGPA margin over the stricter of the policy/JD floor (same rule as eligibility), and "No active backlogs". No LLM. `_new_application` saves them inside the application's `match_json` snapshot (key `highlights`, no migration); `to_out` strips that key before building `ScoreBreakdown` and falls back to `skill_highlights(breakdown)` for older applications. Shown to staff and recruiters on `ApplicationCard`.

#### `cv_tips.py`: CV improvement tips
The gaps are the missing skills from the verified score breakdown (code); one LLM call writes a suggestion per gap and may cite a related resume line. That quote must pass `scoring.quote_in_resume`, else it is dropped and the tip is `build` (gain the skill) instead of `surface` (make existing work visible). Skills the LLM adds are ignored; skills it skips get a fallback suggestion. The prompt forbids advising students to claim skills they haven't used. Results are cached in `score_cache` under a separate key (`kind: cv-tips`, `TIPS_VERSION`, model, prompt, resume hash). The CV is never edited.

#### `llm.py`: OpenAI structured extraction
- `EXTRACT_PREAMBLE`: "extract only stated facts; null/[] when absent; never invent".
- `get_openai_client()`; `extract_structured(text, schema, instructions)`: structured outputs, temperature 0. Missing key → 500; OpenAI errors → 502 (`openai_error_to_http`, never leaks the key); schema refusal → 422.

#### `embeddings.py`, `chunking.py`, `vectorstore.py`, `index_sync.py`: citation index
- `embeddings.embed_texts(texts)`: text-embedding-3-small; errors → 502.
- `chunking.chunk_text(text, size, overlap)`: `langchain-text-splitters` recursive splitter. Policies and JDs use clause-sized chunks (`CLAUSE_CHUNK_SIZE` 400, overlap 0).
- `vectorstore`: `get_collection` (cosine); `ingest_document` (embed **first**, then delete the doc's old chunks, then upsert, so a failed embed leaves old data intact); `retrieve(collection, query, k, where)`; `_embed_query` (in-process cache of query embeddings: citation queries are a handful of fixed descriptions); `_client` (lock-guarded: parallel ranking threads raced creating Chroma's client); `reset_clients`. Collections: `policies`, `jds` (`resumes` is defined but no longer filled; scoring reads full text from the DB).
- `index_sync.sync_index()`: re-embeds any policy/JD with no chunks in the index. Runs in the background at startup because hosted disks are wiped on deploy. Idempotent.

#### `pdf.py`: document input
- `SUPPORTED_EXTENSIONS` = `.pdf`, `.txt`; anything else → 415.
- `extract_pdf_text` (pypdf; unreadable → 422), `normalize_newlines`, `text_from_upload` (UTF-8 with BOM handling; bad encoding → 422), `resolve_source_text(text, file)` (exactly one source).

#### `storage.py`, `supabase_admin.py`: Supabase REST
- `storage.resume_object_path(student_id, filename, data)` → `<student_id>/<sha256[:16]><ext>` (content-addressed, so versions are immutable). `upload_resume` (upsert), `signed_resume_url` (60 s). Disabled without Supabase config. Errors → 502 with the status code only.
- `supabase_admin.invite_user(email, redirect_to)` → `POST /auth/v1/invite?redirect_to=…`; returns the new user id; already registered → 409. `routers/admin._set_password_url` builds `redirect_to` (`<origin>/auth/callback?next=set-password`) only from an `Origin` header that is in `CORS_ORIGINS`, so a forged header can't redirect invitation emails.
- Both expose `_http_client()` so tests can inject `httpx.MockTransport`.

---

## 7. Data model

The Postgres schema lives in `supabase/migrations/` and is the source of truth. `db.SQLITE_SCHEMA` mirrors it for tests and the offline demo. **Change both together.**

| Migration | Adds |
|---|---|
| `20261105000000_init.sql` | `profiles` (role check), `policies`, `jds`, `students`; `handle_new_user` trigger (every sign-up → `student`); `has_role(variadic text[])` (security definer); RLS on every table; private `resumes` bucket + read policies |
| `20261117000000_auto_apply.sql` | `auto_apply_preferences`, `applications` (`unique(student_id, jd_id)`, `release_at > created_at`, `decided_at` set iff not pending), `notifications`; RLS (recruiters read only *submitted* applications for their own JDs); recruiter storage read policy |
| `20261117120000_score_cache.sql` | `score_cache` (backend-only: RLS on, no policies) |
| `20261120000000_student_cv.sql` | Students without a CV (`parsed_json` default `{}`), `resume_updated_at` |

| Table | Key columns | Written by |
|---|---|---|
| `profiles` | `id` (= auth user), `email`, `role` | sign-up trigger, `set_profile_role` |
| `policies` / `jds` | `id` (content hash), `source_text`, `rules_json` / `requirements_json`, `created_by` | upload routers |
| `students` | `id` (stable: hash of email, else name+branch+batch; older rows keep their original id), profile fields, `resume_text`, `parsed_json`, `resume_path`, `resume_updated_at`, `email` | `POST /students` (office, academic fields), `PUT /students/me/resume` (student, CV) |
| `auto_apply_preferences` | `student_id`, `enabled`, `min_score`, `excluded_companies` | `PUT /me/auto-apply` |
| `applications` | `status`, `score`, `match_json` (snapshot), `resume_path` + `resume_sha` (pin), `release_at`, `decided_at` | auto-apply service |
| `notifications` | `student_id`, `application_id`, `kind`, `message`, `read_at` | in the same transaction as each application change |
| `score_cache` | `cache_key`, `breakdown_json`, `model`, `student_id`, `jd_id` | `score_student_cached` |

A new CV keeps the **same student id**; applications pin the CV that was scored (storage path + text hash), and stored files are never overwritten, so a pinned CV can't change underneath an application.

---

## 8. API reference

Interactive docs at `/docs` when the API is running. "Staff" = officer + admin.

| Method | Path | Who | Handler |
|---|---|---|---|
| GET | `/health` | public | `main.health` |
| POST | `/policies` | staff | `policies.create_policy` |
| GET | `/policies`, `/policies/{id}` | any signed-in user | `policies.list_policies_endpoint`, `get_policy_endpoint` |
| POST | `/jds` | officer, admin, recruiter (own JDs) | `jds.create_jd` |
| GET | `/jds`, `/jds/{id}` | any signed-in user | `jds.list_jds_endpoint`, `get_jd_endpoint` |
| POST | `/students` | staff | `students.create_student` |
| GET | `/students`, `/students/{id}` | staff | `students.list_students_endpoint`, `get_student_endpoint` |
| PUT | `/students/{id}` | staff | `students.update_student_endpoint` → `db.update_student_record` (academic fields only; branch/batch normalised; email unique across students, required while there's no CV; id and CV unchanged) |
| GET | `/students/me` | student | `students.get_my_record` |
| PUT | `/students/me/resume` | student (own linked record) | `students.upload_my_resume` |
| GET | `/students/{id}/resume` | staff, owning student | `students.get_resume_link` |
| POST | `/match` | staff, student (self only) | `match.match` |
| GET | `/jds/{id}/ranked?policy_id=&refresh=` | staff | `match.ranked` |
| GET / PUT | `/me/auto-apply` | student | `applications.get_my_preferences` / `set_my_preferences` |
| GET | `/me/jobs?policy_id=` | student | `applications.my_jobs` (every JD with the student's rule-based eligibility, deadline, closed flag and own application; policy defaults to the newest; no LLM calls) |
| POST | `/me/jobs/{jd_id}/apply?policy_id=` | student | `applications.apply_to_job` → `auto_apply.apply_manually` (201; 409 with the reason when not allowed) |
| POST | `/me/jobs/{jd_id}/cv-tips?policy_id=` | student | `applications.my_cv_tips` → `cv_tips.cv_tips` (eligible + CV required; nothing missing → no AI call) |
| GET | `/me/applications` | student | `applications.my_applications` |
| POST | `/applications/{id}/withdraw` | student (owner) | `applications.withdraw` |
| GET | `/me/notifications` | student | `applications.my_notifications` |
| POST | `/me/notifications/read` | student | `applications.mark_read` |
| POST | `/jds/{id}/auto-apply?policy_id=` | staff | `applications.run_auto_apply` |
| GET | `/applications?jd_id=&status=` | staff; recruiter (submitted, own JDs) | `applications.list_applications` |
| GET | `/applications/{id}/resume` | staff, owner, recruiter once submitted | `applications.application_resume` |
| GET | `/admin/users` | admin | `admin.list_users` |
| POST | `/admin/invite` | admin | `admin.invite` |
| PUT | `/admin/users/{id}/role` | admin | `admin.change_role` |
| GET | `/admin/me` | any signed-in user | `admin.whoami` |

**Error codes:** 400 nothing supplied · 401 missing/invalid/expired token · 403 role not allowed · 404 unknown id *or not yours* (same response, so ids can't be probed) · 409 conflict (too late to withdraw, deadline passed, already registered) · 415 unsupported file · 422 bad input or unreadable file · 500 unexpected (JSON, with CORS) · 502 OpenAI/Supabase unavailable · 503 database or auth keys unreachable.

---

## 9. Frontend reference

Next.js 16 (App Router), Tailwind 4, `lucide-react` icons, `@supabase/supabase-js` for sign-in only. Every page is a client component; there is no server-side data fetching. Component classes in `app/globals.css` (`.card`, `.btn`, `.input`, `.chip`, …) sit inside `@layer components` so Tailwind utilities on an element (`lg:hidden`, `bg-rose-600`) override them; keep new ones there.

**Theme and dark mode.** `globals.css` redefines Tailwind's colour names as theme variables: `slate-*` is a warm neutral scale, plus `page` (background), `surface` (cards, bars, inputs: use `bg-surface`, not `bg-white`) and `ink` (the always-dark login panel). `:root.dark` redefines the same names (neutrals invert; `brand`/`emerald`/`rose`/`amber` tints become dark washes and text shades become light), so components need almost no `dark:` classes. Dark mode is the `.dark` class on `<html>`: `ThemeToggle` sets it and saves the choice in `localStorage`; `THEME_INIT_SCRIPT` in `app/layout.tsx` applies it before first paint (no light flash), defaulting to the OS setting. Text that must stay light on the always-dark panel uses fixed Tailwind colours (`text-white`, `text-indigo-100`), not theme names. `text-white` is never themed, so it stays white on coloured buttons.

### 9.1 `web/lib/`
| File | Exports | Purpose |
|---|---|---|
| `supabase.ts` | `supabase`, `supabaseConfigured`, `authCallbackUrl`, `friendlyAuthError` | Supabase client (publishable key, implicit flow so email links work across devices). `authCallbackUrl(next)` builds the email-link return URL; `friendlyAuthError` maps auth errors to readable text. |
| `api.ts` | `api<T>(path, init)`, `ApiError` | Fetch wrapper: adds the bearer token, sets JSON headers, turns FastAPI errors (`detail`) into readable messages, maps network failure to a clear "no response" message. |
| `auth.tsx` | `AuthProvider`, `useAuth`, `RequireRole`, `homeFor`, `FullPageSpinner` | Session + profile context. The role comes from `GET /admin/me`, never from the token. `RequireRole` hides pages from the wrong roles (UX only; the API enforces). `homeFor(role)` picks the landing page. |
| `useApi.ts` | `useApi<T>(path, {revalidate})`, `invalidate(...prefixes)` | GET with an in-memory stale-while-revalidate cache; de-duplicates in-flight requests; cleared on sign-in/out. `revalidate:false` for expensive calls (rankings). Call `invalidate` after writes. |
| `time.ts` | `useNow`, `formatDateTime`, `timeUntil`, `timeAgo` | Countdown and relative-time helpers. |
| `types.ts` | all API types | Hand-mirrored from `app/schemas.py`. |

### 9.2 `web/components/`
| File | Exports | Purpose |
|---|---|---|
| `AppShell.tsx` | `AppShell` | Staff/recruiter layout: sidebar (desktop) / slide-out menu (mobile), role-filtered nav (`LINKS`), user card with sign-out. Students get `StudentShell` instead. No shell on the account pages (`AUTH_PAGES`: login, sign-up, forgot/set password, callback). |
| `StudentShell.tsx` | `StudentShell` | Student layout: top bar (brand, `NotificationBell`, account menu with sign-out), left icon rail (Jobs, Applications, Profile & CV, Auto-apply), slide-out menu on mobile. |
| `NotificationBell.tsx` | `NotificationBell` | Unread badge + dropdown over `/me/notifications`, "Mark all read", refreshes every 60 s. |
| `JobBoard.tsx` | `JobBoard` | Student job board over `GET /me/jobs`: `jobStatus` (Applied / Sent to company / Withdrawn / closed / eligible / not eligible), filters, list + detail (stacked on mobile), `DescriptionTab` (`GET /jds/{id}`), `EligibilityTab`, `MatchTab` (`POST /match`). |
| `AutoApplySettings.tsx` | `AutoApplySettings` | Student auto-apply preferences form (switch, min score, excluded companies). |
| `StudentCvCard.tsx` | `StudentCvCard` | Upload/replace/open the student's own CV. |
| `StudentEditForm.tsx` | `StudentEditForm` | Staff form for a student's academic record (`PUT /students/{id}`); warns when the login email changes. |
| `NotLinked.tsx` | `NotLinked` | Shown when a student account has no matching record (`/students/me` → 404). |
| `ThemeToggle.tsx` | `ThemeToggle`, `THEME_INIT_SCRIPT` | Light/dark switch (student top bar beside the bell, staff sidebar and mobile header, top-right on account pages); saved in `localStorage`. |
| `AuthCard.tsx` | `AuthCard`, `passwordProblem`, `MIN_PASSWORD_LENGTH` | Centered card for the account pages, and the shared password rule (8+ characters, both fields match). |
| `ui.tsx` | `ErrorBox`, `SuccessBox`, `Warnings`, `Chip`, `Chips`, `PageHeader`, `StatCard`, `EmptyState`, `Spinner`, `Skeleton`, `CardSkeletons`, `Avatar`, `display`, `errorText`, `Tone` | Shared UI primitives. |
| `MatchResultCard.tsx` | `MatchResultCard`, `ScoreRing` | One student × one JD: eligibility chips, failed rules (keyed by rule+source), skills, evidence quotes, citations. |
| `PolicyPicker.tsx` | `PolicyPicker`, `policyLabel` | Policy selector. |
| `AutoApplyPanel.tsx` | `AutoApplyPanel` | Officer's "Run auto-apply" with confirm + created/skipped summary. |
| `ApplicationCard.tsx` | `ApplicationCard`, `StatusChip` | One application for a student/staff/recruiter viewer: status, countdown bar, "Why they stand out" (`highlights`, staff/recruiter only), matched/missing required skills, pinned-resume link, withdraw with confirm. |

### 9.3 `web/app/` (pages)
| Route | Roles | What it does |
|---|---|---|
| `/` (`page.tsx`) | all | Redirects to `/login` or the role's home page. |
| `/login` | public | Sign-in; links to sign-up and forgot password; button disabled until hydrated. |
| `/signup` | public | Student self sign-up (email confirmation required: the account links to a record by email). Same response whether or not the email exists. |
| `/forgot-password` | public | Sends a reset link; same response whether or not the account exists. |
| `/auth/callback` | public | Landing page for every email link; `?next=set-password` (reset, invite) or `confirmed` (sign-up); shows a clear message for expired links. |
| `/set-password` | signed in via an email link | Choose a new password (`supabase.auth.updateUser`). |
| `/jobs` | officer, admin | Policy picker, job cards, ranking results (stats, filter tabs, Re-run / Re-score with AI, cache line), auto-apply panel. |
| `/students` | officer, admin | Searchable student table; detail panel with skills, projects, resume link and **Edit details** (`StudentEditForm`, `PUT /students/{id}`). |
| `/upload` | officer, admin, recruiter | Tabs: policy, JD (recruiters see only this), student; drag-and-drop; shows warnings. `?tab=student` deep-links. |
| `/applications` | officer, admin, recruiter | Application tracking; status tiles (staff); `?jd=` filter; refreshes every 60 s. |
| `/me` | student | Job board (`JobBoard`): list with status/sort/search filters and All/Applied tabs, detail with application banner and Description / Eligibility / My match tabs. |
| `/me/applications` | student | Own applications (`ApplicationCard`) with withdraw. |
| `/me/profile` | student | Read-only academic record, CV skills, `StudentCvCard`. |
| `/me/auto-apply` | student | `AutoApplySettings`; warns when no CV is uploaded. |
| `/admin` | admin | Role counts, invite form, role changes. |

---

## 10. Scripts

| Script | Purpose |
|---|---|
| `get_token.py --email` | Signs in (hidden password prompt) and prints an access token. In PowerShell: `$env:PLACEMENT_TOKEN = uv run python scripts/get_token.py --email …`. |
| `seed_sample.py` | Loads `data/sample/` (policy, 3 JDs, 10 students) into a running API, ranks every JD and diffs against `expected_outcomes.txt`. Live OpenAI calls. |
| `load_generated.py [--dry-run]` | Loads `data/generated/` (JD PDFs + students) into a running API. No ranking. |
| `import_jd_bundle.py <file>` | Splits a Gemini JD bundle into `.txt` + `.pdf`, merges the answer key, cross-checks skills/CGPA/deadlines against the text. |
| `import_student_bundle.py <file>` | Imports Gemini student JSON into resumes + `students.json` + answer key; reports unproven true skills, decoy mentions, unknown branches. |
| `text_to_pdf.py <txt>` | Dependency-free text → PDF writer; verifies the round trip with the app's PDF parser. |
| `encode_db_password.py` | URL-encodes a database password for `DATABASE_URL` (hidden input). |

---

## 11. Tests

`uv run pytest` runs about 230 tests in under 20 seconds, fully offline.

**Rules of the suite**
- **LLM, embeddings and Supabase HTTP are always mocked.** Nothing may call OpenAI or the real Supabase project.
- `tests/conftest.py::make_test_settings` passes `_env_file=None`, so tests **never read `.env`** (it points at the real project). It also turns off the release sweep and the startup index sync.
- The default user is an injected **admin** (`app_and_user` fixture overrides `get_current_user`); `login_as(role, email=…, user_id=…)` switches roles.
- `fake_embed_texts` gives deterministic vectors.
- Time-dependent tests replace `auto_apply.utcnow` with a fake clock.

| File | Covers |
|---|---|
| `test_auth.py` | Real ES256 JWT verification with a throwaway key: valid token, ignored role claims, expiry/audience/issuer, wrong key, HS256 rejected, missing profile, JWKS outage, dev bypass rules |
| `test_roles.py` | Role matrix for every endpoint, student self-access, recruiter JD ownership, invites, role changes, storage paths and signed URLs |
| `test_eligibility.py` | Every rule, stricter CGPA, multi-source failures, compound/abbreviated/"all"/"circuit" branch rules |
| `test_normalize.py` | Branch aliases, compound splitting, unrestricted phrases, batch years |
| `test_grounding.py` | Dropping unstated batch/CGPA rules |
| `test_scoring.py` | Quote verification (fragments, punctuation, case), skill-mention heuristic, formula, omitted skills |
| `test_score_cache.py` | Cache hit/miss, refresh, shared cache, eligibility never cached, key components |
| `test_match.py` | `/match` and `/ranked`: scoring, citations, sorting |
| `test_auto_apply.py` | Preferences, the run, pinning, notifications, withdraw window, release, idempotency, deadlines and parsing, recruiter visibility, roles |
| `test_student_edit.py` | Office edits: fields and normalisation, CV kept, eligibility uses new CGPA at once, email change moves the login link, duplicate email 409, email required without a CV, validation, roles |
| `test_student_cv.py` | Office records without a CV, student CV upload/replace, stable ids, no-CV scoring and auto-apply skip, storage failure leaves no record |
| `test_my_jobs.py` | `GET /me/jobs`: eligibility per job, application status, closed deadlines, policy default/unknown, roles, no LLM calls |
| `test_highlights.py` | Highlight lines (coverage, stricter CGPA floor, backlogs), snapshot on new applications, fallback for older ones |
| `test_apply_and_tips.py` | Manual apply (staged, `source`, twice, re-apply after withdrawal (same row, fresh snapshot; not once sent or past the deadline; never by auto-apply), ineligible without AI calls, closed, no CV, roles) and CV tips (only missing skills, quote verification, cache, nothing missing, ineligible) |
| `test_index_sync.py` | Rebuilding a wiped index, idempotency, non-fatal failure |
| `test_performance.py` | Profile cache, Chroma client race, citation query cache |
| `test_ingest_errors.py` | Config, OpenAI failures → 502, upload validation, normalisation at ingest, line endings, clause chunking |
| `test_cors.py` | Allowed/refused origins, 500s still carry CORS |
| `test_policies.py`, `test_jds.py`, `test_students.py`, `test_vectorstore.py`, `test_health.py` | Basic ingest and storage paths |

A good test proves the change *matters*: before relying on a new test, break the code it guards and confirm it fails.

---

## 12. Recipes for common changes

**Add an endpoint**
1. Add request/response models in `app/schemas.py` and mirror them in `web/lib/types.ts`.
2. Add the route to the right router with an explicit `Depends(require_role(...))`, `staff_only` or `any_user`. Never leave a route without a role check.
3. Put logic in `app/services/` and SQL in `app/db.py`, not in the router.
4. Add the route to the role matrix in `tests/test_roles.py` and write behaviour tests.

**Change the database schema**
1. New file `supabase/migrations/<timestamp>_<name>.sql`: tables, constraints, `enable row level security`, `revoke … from anon`, and policies.
2. Mirror the tables in `db.SQLITE_SCHEMA` (and `_SQLITE_ADDED_COLUMNS` for new columns on existing tables).
3. If the API needs the table at startup, add an existence check in `db.init_db` with the migration name in the error.
4. Apply with `npx supabase@latest db push --linked` **before** deploying code that needs it.

**Change how scores are computed** (validation, formula, prompt)
- Prompt or skill-list changes already change the cache key.
- Any change to `quote_in_resume`, `quote_mentions_skill`, `validate_evidence`, `compute_score` or `_dedupe`: **bump `SCORING_VERSION`** in `scoring.py`, or stale scores will be served from the cache.

**Teach the app a new branch name**
Add a lowercase alias to `_BRANCH_ALIASES` in `normalize.py` (keys: lowercase, `&` → `and`, punctuation collapsed to spaces, `engg` → `engineering`). Add a case to `test_normalize.py`. Stored rules are re-normalised at check time, so nothing needs re-uploading.

**Extract a new field from JDs or policies**
Add it to `JDRequirements`/`PolicyRules`, mention it in `JD_INSTRUCTIONS`/`POLICY_INSTRUCTIONS`, and, if it becomes an eligibility rule, enforce it in `eligibility.py` (in code), add a `RULE_DESCRIPTIONS` entry, and ground it in `grounding.py` if a hallucinated value would be harmful.

**Add a page**
Create `web/app/<route>/page.tsx` as a client component wrapped in `RequireRole`, fetch with `useApi`, call `invalidate` after writes, and add a nav entry to `LINKS` in `AppShell.tsx`.

---

## 13. Deployment and operations

- **API on Render** from `render.yaml`: free plan, Singapore region, build `uv sync --frozen --no-dev`, start `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health check `/health`. Secrets are set in the Render dashboard.
- **Web on Vercel**, project root `web/`. `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_API_URL` are baked in at build time, so changing one needs a redeploy.
- **`CORS_ORIGINS`** on Render must be a JSON list, e.g. `["https://your-app.vercel.app"]`, with no trailing slash.
- **Supabase Auth → URL Configuration:** Site URL and Redirect URLs point at the Vercel domain.
- **Ephemeral disk:** Chroma is rebuilt from Postgres at startup (`index_sync`). Look for `Vector index: N documents checked, M re-embedded` in the logs.
- **Free-plan sleep:** the first request after 15 idle minutes takes ~1 min. Auto-apply releases still happen on time because every read of applications releases due ones.
- **Migrations are manual** and must be applied before code that needs them; the API refuses to start otherwise.
- Every push to `main` redeploys both services.

---

## 14. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Web app: "No response from the API" | API down, asleep or crashed; or a CORS mismatch | Check `/health`; check the API logs; check `CORS_ORIGINS` matches the web origin exactly |
| Page stuck on "Loading…" in dev | Opened via the network IP (`172.x…:3000`) instead of `localhost:3000` | Use `http://localhost:3000` |
| API won't start: "tables are missing" | A migration isn't applied | `npx supabase@latest db push --linked` |
| API won't start: settings error on `cors_origins` | `CORS_ORIGINS` isn't a JSON list | Use `["https://…"]` with double quotes |
| 401 "Token expired." in scripts | Tokens last ~1 hour | Re-run `get_token.py` in the same terminal |
| 503 "Database unavailable." | Wrong `DATABASE_URL` or network | Use the **Session pooler** URI; URL-encode special characters in the password (`scripts/encode_db_password.py`) |
| Everyone ineligible for a JD | A branch rule the app can't read | Check the JD's stored `allowed_branches`; add an alias in `normalize.py` |
| Citations empty after deploy | Index sync still running or failed | Check logs for "Vector index"; it retries on the next restart |
| Score looks stale after changing scoring code | Cache key didn't change | Bump `SCORING_VERSION`, or use `?refresh=true` / *Re-score with AI* |
| Duplicate-key warning in React | Two list items with the same key | Key by a unique combination (e.g. rule + source) |
