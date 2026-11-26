# Campus Placement Agent

Backend for a campus placement system. A placement officer uploads a placement policy and a job description; students are checked for eligibility and scored against the JD from their resumes. The officer gets a ranked list with matched/missing skills, the resume evidence behind each match, and, for ineligible students, the exact rule they failed plus the policy or JD clause it comes from.

**Honest framing:** the pipeline (parse JD → filter → score → threshold → staged apply) is a deterministic workflow with LLM steps, not an autonomous agent. The LLM extracts rules and finds resume evidence; every decision (eligible, score, apply, release) is made by code.

**Guides:** [Product guide](docs/PRODUCT_GUIDE.md) (what it does and why to trust it) · [Contributor guide](docs/CONTRIBUTOR_GUIDE.md) (every module, file and function).

## How it decides

| Step | Who decides | Notes |
|---|---|---|
| Parse policy / JD / resume | LLM (gpt-4o-mini, structured outputs, temperature 0) | Validated against Pydantic schemas; branches and batches are then normalized in code (`CSE`, `2027`) |
| Rule grounding | Code | An extracted batch or CGPA rule is dropped (and returned as a `warning`) unless the document states it, e.g. a 2026 deadline is not read as "batch 2026" |
| Eligibility | Plain Python | CGPA (stricter of policy and JD), active backlogs, branch, batch, placed-student rule. Every failure is reported. Unstated rules are not enforced |
| Skill evidence | LLM | Per JD skill: evidenced yes/no plus a verbatim resume quote |
| Evidence check | Code | Quote must appear verbatim in the resume (case, whitespace and edge punctuation ignored; glued sentences must each appear in order) and mention the skill; skills the LLM omits count as missing |
| Score | Code | `100 × (0.75 × required coverage + 0.25 × preferred coverage)`; no preferred skills → required only; no required skills → `null` |
| Citations | RAG (ChromaDB) | For each failed rule, the top-2 chunks from the policy or JD the rule came from (policies and JDs are chunked by paragraph, ~400 chars) |
| Auto-apply | Code | Opted-in students who are eligible and score ≥ max(`AUTO_APPLY_THRESHOLD`, their own bar) get a *pending* application; it is sent only after a withdraw window (see below) |

Known limits: the "quote mentions the skill" check is a token heuristic and can reject paraphrased evidence (it errs toward under-scoring). Scores are cached (below), so only a new resume/JD pair costs an LLM call.

Performance, measured against the hosted database (region ap-northeast-1):

| | Before | After |
|---|---|---|
| Database call | ~2.3 s (new connection + query + COMMIT) | ~0.27 s (pooled connection, autocommit, one round trip) |
| Role lookup per request | one DB call | cached 60 s; cleared at once when an admin changes the role through the API |
| Ranking one JD (live OpenAI) | 10.6 s | 4.1 s first time (parallel scoring), **~1 s after** (score cache, 0 AI calls) |

**Score cache.** The only LLM call per student per JD is the evidence step, and its output depends only on the resume text, the JD's skill lists, the model, the prompt and the validation code. The backend stores the *verified* breakdown under a SHA-256 of exactly those inputs (`score_cache` table). Change any input and the key changes, so a stale score is never read; there is no invalidation logic to get wrong. Eligibility is never cached: it is cheap and must follow the current policy. `GET /jds/{id}/ranked?refresh=true` (the *Re-score with AI* button) ignores and overwrites the cache. Each result says whether its score came from the cache or a fresh call. Bump `SCORING_VERSION` in `app/services/scoring.py` when the validation/score code changes.

## Setup

Python 3.12, managed with `uv`.

```bash
uv sync --group dev
```

Copy `.env.example` to `.env` and fill it in (never commit `.env`). With only `OPENAI_API_KEY` set and `DEV_AUTH_BYPASS=true`, the app runs fully offline on SQLite (every request acts as admin). Adding the Supabase values switches on real auth, Postgres and resume storage.

## Supabase (auth, Postgres, resume storage)

**How access works**

- **Auth:** users log in through Supabase Auth and get a signed access token (JWT). The API verifies it against the project's public keys (JWKS, ES256), plus expiry, audience and issuer. No shared secret is stored.
- **Roles:** stored in `public.profiles.role` and read on every request. Never taken from the token or `user_metadata`, which users can edit.
- **Sign-up:** every new user starts as `student`, set by a database trigger. Officers, recruiters and admins are granted by an admin (`POST /admin/invite` or `PUT /admin/users/{id}/role`).
- **RLS:** enabled on every table, for direct client access (the future Next.js app). The API uses the secret key, which bypasses RLS, so every endpoint also checks roles in code (`require_role` in `app/auth.py`).
- **Resumes:** go to a private Storage bucket from memory, under content-addressed paths (one immutable path per resume version). They are only readable through 60-second signed links. Resumes are not embedded in the local vector store.

| | admin | officer | recruiter | student |
|---|---|---|---|---|
| Upload policy | ✓ | ✓ | | |
| Upload JD | ✓ | ✓ | own JDs | |
| Read policies / JDs | ✓ | ✓ | ✓ | ✓ |
| Add / list / read students, `/ranked` | ✓ | ✓ | | |
| `/students/me`, `/match` and resume link for **own** record | | | | ✓ |
| Run auto-apply for a JD, see all applications | ✓ | ✓ | | |
| See **sent** applications to own JDs (and the pinned resume) | | | ✓ | |
| Opt in to auto-apply, withdraw own pending applications | | | | ✓ |
| Invite users, change roles | ✓ | | | |

A student's record is linked by the email the officer enters, matched against the student's verified login email.

**One-time setup**

1. Create a free project at supabase.com. New projects use asymmetric JWT signing keys (ES256), which this API expects.
2. Put `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` and `DATABASE_URL` in `.env`. Use the **Session pooler** URI from the dashboard's *Connect* button.
3. Dashboard -> SQL Editor: paste and run `supabase/migrations/20261105000000_init.sql`.
4. Dashboard -> Authentication -> Users -> *Add user*: create your own account (auto-confirm).
5. SQL Editor: make yourself the first admin:

   ```sql
   update public.profiles set role = 'admin' where email = 'you@example.com';
   ```

   If you created users *before* running the migration, backfill their profiles first:

   ```sql
   insert into public.profiles (id, email) select id, email from auth.users on conflict do nothing;
   ```

6. Get a token, then paste it into *Authorize* in `/docs`:

   ```bash
   uv run python scripts/get_token.py --email you@example.com
   ```

## Run

```bash
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs.

| Endpoint | Purpose |
|---|---|
| `POST /policies`, `POST /jds` | Form field `text` **or** a `.pdf`/`.txt` `file` (not both) |
| `PUT /jds/{id}/deadline` | Extend or shorten a job's deadline (recruiter: own jobs; officer/admin: any). Shortening moves pending applications earlier and notifies the students |
| `PUT /jds/{id}`, `DELETE /jds/{id}` | Admin: edit a job's details (JSON, same fields as the extracted requirements) or remove the job with its applications |
| `GET` / `PUT /admin/settings` | Admin: read or change the college-wide minimum auto-apply score (`auto_apply_threshold`, 0–100; default from `AUTO_APPLY_THRESHOLD`) |
| `GET /auto-apply/runs?jd_id=` | Staff: recorded auto-apply runs (automatic and manual) with who was applied and why others were skipped |
| `POST /students` | Form fields `name`, `email`, `branch`, `batch`, `cgpa` (0–10), `active_backlogs`, `is_placed`, plus a `.pdf`/`.txt` `resume` |
| `GET /policies`, `/jds`, `/students` and `GET /{resource}/{id}` | Discover ids, inspect extracted JSON |
| `PUT /students/{id}` | Staff edit a student's academic record (JSON: name, email, branch, batch, cgpa, active_backlogs, is_placed); the CV and id never change |
| `GET /students/me`, `GET /students/{id}/resume` | A student's own record; a short-lived signed link to the resume file |
| `POST /match` | `{jd_id, student_id, policy_id}` → eligibility, score breakdown, citations |
| `GET /jds/{jd_id}/ranked?policy_id=...` | Eligible students by score, then ineligible students with failed rules and citations |
| `GET /admin/users`, `POST /admin/invite`, `PUT /admin/users/{id}/role`, `GET /admin/me` | List users and roles, invite with a role, change a role, show who you are |

Error codes: `400` nothing supplied, `401` missing/invalid/expired token, `403` your role can't do this, `404` unknown id (or not yours), `409` conflict, `415` unsupported file type, `422` bad input or unparseable file, `502` OpenAI or Supabase unavailable, `503` database or auth keys unreachable.

Demo flow: with the server running, load the sample policy, 3 JDs and 10 students from `data/sample/`, rank every JD and compare against `data/sample/expected_outcomes.txt`. With Supabase, pass an officer or admin token; offline, run the server with `DEV_AUTH_BYPASS=true` and omit it:

```bash
uv run python scripts/seed_sample.py --token <access token>
```

This makes real OpenAI calls (about 20 per run). Re-running is safe: ids are content hashes.

## Staged auto-apply

The feature that saves students and officers the most time, built so nothing is sent behind a student's back.

1. **Opt in.** A student turns auto-apply on and can raise the minimum score (never below the college threshold) and exclude companies. Off by default.
2. **Run.** Automatically, in the background, right after a JD is uploaded (against the newest policy; `AUTO_APPLY_ON_UPLOAD`, on by default), or when an officer clicks *Run auto-apply* on a job. For each opted-in student, code checks, in order: already applied to this job (auto-apply never re-sends a withdrawn application; the student may re-apply manually from the job board), excluded company, the policy's `max_applications_per_student`, then the same eligibility and evidence-based score as `/ranked`. Qualifiers get a **pending** application and a notification; everyone else is listed with the reason.
3. **Pin.** Each application stores the resume version as scored (content-addressed file path + SHA-256 of the text) and the score breakdown with its verified quotes. A later resume upload doesn't change what was sent.
4. **Withdraw window.** The student can withdraw until `release_at = min(created + 24 h, JD deadline − 6 h)`. A run is refused if that leaves under an hour (or the deadline has passed). Deadlines are parsed by code ("November 20, 2026", "20/11/2026", ISO); a date means 23:59 IST.
5. **Release.** One conditional `UPDATE … WHERE status = 'pending' AND release_at <= now` marks applications *submitted* and notifies the student. It runs every 60 s and before every read of applications, so a status is never stale. Because release and withdraw are both single conditional updates, they can't both win.
6. **Recruiters** see an application, and its pinned resume, only once it's submitted, and only for jobs they posted (enforced in the API and by RLS).

```
pending ──(student withdraws before release_at)──▶ withdrawn   (final)
   └─────(release_at passes)─────────────────────▶ submitted   (final)
```

Schema: `supabase/migrations/20261117000000_auto_apply.sql` (`auto_apply_preferences`, `applications`, `notifications`, RLS). Apply with `npx supabase@latest db push --linked`. Limits: notifications are in-app only (no email yet), and "submitted" means visible to the recruiter in this system; there is no integration with external job portals.

| Endpoint | Who | Purpose |
|---|---|---|
| `GET` / `PUT /me/auto-apply` | student | Read / set preferences |
| `GET /me/jobs?policy_id=` | student | Job board: every JD with own eligibility, deadline and application (no AI calls) |
| `POST /me/jobs/{id}/apply` | student | Apply yourself: same staged pipeline as auto-apply (rules, score snapshot, withdraw window), no score bar |
| `POST /me/jobs/{id}/cv-tips` | student | Skills the job asks for that the CV doesn't show (from the verified score), with an AI suggestion per gap; cited CV lines are verified |
| `GET /me/applications`, `POST /applications/{id}/withdraw` | student | Own applications; withdraw while pending |
| `GET /me/notifications`, `POST /me/notifications/read` | student | Notification feed |
| `POST /jds/{id}/auto-apply?policy_id=` | officer, admin | Run for a job; returns created + skipped with reasons |
| `GET /applications?jd_id=&status=` | officer, admin; recruiter (sent, own jobs) | Track applications |
| `GET /applications/{id}/resume` | staff, owner, recruiter once sent | Signed link to the pinned resume |

## Web app (Next.js)

`web/` is a Next.js + Tailwind front end over the same API. The browser uses Supabase only to sign in; every data call goes to FastAPI with the user's token, so roles are enforced in one place (`require_role`). Pages hide what a role can't use, but that's convenience: the API refuses it anyway.

| Page | Role | What it does |
|---|---|---|
| `/login` | everyone | Email + password sign-in (Supabase Auth), links to sign-up and password reset |
| `/signup`, `/forgot-password`, `/set-password`, `/auth/callback` | everyone | Student sign-up with email confirmation, password reset, invited staff choosing a password, and the landing page for all email links |
| `/jobs` | officer, admin | Pick a policy and a JD, rank students: score, matched/missing skills, verified resume quotes, failed rules with the policy/JD clause |
| `/students` | officer, admin | Student list, parsed skills, 60-second signed link to the resume file |
| `/upload` | officer, admin (recruiter: JD only) | Policy, JD and student forms; shows grounding warnings |
| `/me` | student | Job board: every job with eligibility, deadline and application status; detail tabs for the description, failed rules and "My match" |
| `/me/applications`, `/me/profile`, `/me/auto-apply` | student | Own applications with withdraw; academic record + CV upload; auto-apply preferences |
| `/applications` | officer, admin, recruiter | Track applications: pending with countdown, sent, withdrawn |
| `/admin` | admin | Invite users with a role, change roles |

```bash
cd web
npm install
cp .env.local.example .env.local   # Supabase URL, publishable key, API URL; never the secret key
npm run dev                        # http://localhost:3000, with the API running on :8000
```

The API allows browser calls only from `CORS_ORIGINS` (default `http://localhost:3000` and `http://127.0.0.1:3000`).

Tradeoff: the session lives in the browser's localStorage (supabase-js default), which page scripts can read. That's acceptable for a client-rendered app with no third-party scripts. Moving to httpOnly cookies (`@supabase/ssr`) is the upgrade if the app ever renders data on the server.

## Deploy (Render + Vercel + Supabase)

```
browser ──▶ Vercel (Next.js, web/) ──▶ Render (FastAPI, render.yaml) ──▶ Supabase (Postgres, Auth, Storage)
                     └── signs in directly with Supabase Auth ──────────────▲
```

- **API on Render** from `render.yaml` (free plan, Singapore). Build: `uv sync --frozen --no-dev`; health check `/health`.
- **Web on Vercel**, project root `web/`.
- **Vector index:** Render's disk is wiped on every deploy. At startup the API re-embeds any policy/JD that is missing from the index, from the text stored in Postgres (`app/services/index_sync.py`). This runs in the background, so health checks pass at once and citations fill in within seconds.
- **Free plan sleeps** after 15 min idle; the first request then takes ~1 min. Pending auto-apply applications are still released on time: releases also happen on every read. Open the site a minute before a demo, or switch `plan: free` to `starter` in `render.yaml`.
- Measured locally: ~160 MB resident at idle (free plan has 512 MB).

**Steps (one-time)**

1. Commit and push everything to `main`. Check `.env`, `web/.env.local` and `data/real_jds/` are not in the commit (all are git-ignored).
2. **Render** → New → Blueprint → select this repo. Render reads `render.yaml`. Fill the secrets from your `.env`: `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `DATABASE_URL`, and for now `CORS_ORIGINS` = `["http://localhost:3000"]`. Deploy, then open `https://<your-api>.onrender.com/health` → `{"status":"ok"}`.
3. **Vercel** → Add New → Project → import this repo → **Root Directory: `web`**. Environment variables: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (same as `web/.env.local`), and `NEXT_PUBLIC_API_URL` = `https://<your-api>.onrender.com`. Deploy. (`NEXT_PUBLIC_` values are baked in at build time: changing one needs a redeploy.)
4. **Render** → Environment → set `CORS_ORIGINS` to `["https://<your-app>.vercel.app"]` (add `"http://localhost:3000"` too if you still develop locally). Saving redeploys.
5. **Supabase** → Authentication → URL Configuration: Site URL = `https://<your-app>.vercel.app`; Redirect URLs: add `https://<your-app>.vercel.app/**`.
6. Open the Vercel URL and sign in. If the page says "No response from the API", the API is waking up; wait a minute and retry.

After this, every push to `main` redeploys both. Schema changes are not automatic: apply new files in `supabase/migrations/` with `npx supabase@latest db push --linked` **before** pushing code that needs them (the API refuses to start if a table is missing).

## Tests

LLM, embedding and Supabase calls are mocked; tests never read `.env`, so they never touch OpenAI or your Supabase project. Auth tests sign real ES256 tokens with a throwaway key.

```bash
uv run pytest
```

## Roadmap

Done: hosted Supabase (Postgres, Auth with roles, private Storage for resumes, RLS), Next.js front end, staged auto-apply with a withdraw window. Next: email notifications → student-side agent (drive watcher, resume-gap nudges).
