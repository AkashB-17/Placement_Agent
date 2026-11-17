-- Score cache: one row per (resume text, JD skill lists, model, prompt, scoring version).
--
-- Scoring is the only LLM call per student per JD, and its output depends only on those
-- inputs, so the backend stores the verified breakdown under a hash of them. Any change
-- to an input (new resume, re-extracted JD skills, other model, edited prompt, bumped
-- SCORING_VERSION) produces a new key, so stale rows are never read; they just stop
-- being used. Eligibility is not cached: it is cheap and must reflect the current policy.
--
-- Backend-only table: RLS on with no policies, so clients can't read or write it.

create table public.score_cache (
    cache_key text primary key,
    student_id text not null references public.students (id) on delete cascade,
    jd_id text not null references public.jds (id) on delete cascade,
    model text not null,
    breakdown_json jsonb not null,
    created_at timestamptz not null default now()
);

create index score_cache_jd_idx on public.score_cache (jd_id);

alter table public.score_cache enable row level security;
revoke all on public.score_cache from anon, authenticated;
