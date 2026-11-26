-- Students who sign up themselves ask to be added; staff approve instead of typing them in.
--
-- A signed-in student whose verified email isn't on any student record submits their
-- academic details (self-reported). Staff (officer/admin) review the request, correct any
-- value, and approve it, which creates the student record (the office still owns it), or
-- reject it with a note; the student can fix and resubmit. One request per account.
--
-- Backend-only table: RLS on with no policies; the API checks roles.

create table if not exists public.registration_requests (
    user_id uuid primary key references auth.users (id) on delete cascade,
    email text not null,
    name text not null,
    branch text not null,
    batch text not null,
    cgpa real not null check (cgpa between 0 and 10),
    active_backlogs integer not null check (active_backlogs >= 0),
    status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
    submitted_at timestamptz not null,
    decided_at timestamptz,
    decided_by uuid references auth.users (id) on delete set null,
    note text
);

create index if not exists registration_requests_status_idx on public.registration_requests (status, submitted_at);

alter table public.registration_requests enable row level security;
revoke all on public.registration_requests from anon, authenticated;
