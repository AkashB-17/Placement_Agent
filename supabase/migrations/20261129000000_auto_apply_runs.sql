-- A record of every auto-apply run, so staff can see what happened and why.
--
-- Auto-apply runs by itself after each JD upload (trigger 'upload') and when an officer
-- clicks Run auto-apply (trigger 'manual'). Each row keeps the outcome:
--   completed: how many students were applied, and every skipped student with the reason
--              (e.g. "Score 69.6 is below their bar of 70."), plus how many hadn't opted in;
--   skipped:   the run didn't happen, with why (no policy yet, deadline passed or too close);
--   failed:    an unexpected error (details in the API log).
--
-- Backend-only table: RLS on with no policies. Staff read it through the API.

create table if not exists public.auto_apply_runs (
    id text primary key,
    jd_id text not null references public.jds (id) on delete cascade,
    policy_id text,
    trigger text not null check (trigger in ('upload', 'manual')),
    status text not null check (status in ('completed', 'skipped', 'failed')),
    ran_at timestamptz not null,
    applied integer not null default 0,
    skipped jsonb not null default '[]'::jsonb,
    not_opted_in integer not null default 0,
    message text,
    actor uuid references auth.users (id) on delete set null
);

create index if not exists auto_apply_runs_jd_idx on public.auto_apply_runs (jd_id, ran_at desc);

alter table public.auto_apply_runs enable row level security;
revoke all on public.auto_apply_runs from anon, authenticated;
