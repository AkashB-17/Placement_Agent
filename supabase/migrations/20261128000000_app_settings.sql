-- College-wide settings an admin can change from the app (no redeploy).
--
-- One row per setting. The first is auto_apply_threshold: the minimum score (0-100) for
-- auto-apply and the "auto-apply recommended" flag. Students can only set their own bar
-- at or above it. Until an admin sets it, the API uses its AUTO_APPLY_THRESHOLD default.
--
-- Backend-only table: RLS on with no policies, so clients can't read or write it; the
-- API reads it with the server-side key and checks the admin role on writes.

create table if not exists public.app_settings (
    key text primary key,
    value jsonb not null,
    updated_at timestamptz not null default now(),
    updated_by uuid references auth.users (id) on delete set null
);

alter table public.app_settings enable row level security;
revoke all on public.app_settings from anon, authenticated;
