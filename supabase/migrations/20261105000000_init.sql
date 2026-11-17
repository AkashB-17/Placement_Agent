-- Campus Placement Agent: initial schema for hosted Supabase.
--
-- Security model
-- * Roles live in public.profiles.role, never in user_metadata (which users can edit).
-- * Every new auth user gets role 'student' from the trigger below, whatever they send
--   at sign-up. Privileged roles (officer, recruiter, admin) are granted by an admin
--   (POST /admin/invite in the API, or the SQL in README for the first admin).
-- * RLS is enabled on every table. It protects direct client access (the future
--   Next.js app using the publishable key + the user's JWT). The FastAPI backend uses
--   the secret key, which bypasses RLS, so it re-checks roles in code (require_role).
-- * Resumes go to a private Storage bucket; there is no client upload policy, so files
--   can only be written by the backend.
--
-- Apply: Supabase dashboard -> SQL Editor -> paste this file -> Run.
-- Column names match the SQLite schema in app/db.py so both backends share queries.

-- ── Profiles and roles ──────────────────────────────────────────────────────

create table public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    email text,
    full_name text,
    role text not null default 'student'
        check (role in ('student', 'officer', 'recruiter', 'admin')),
    created_at timestamptz not null default now()
);

create index profiles_email_idx on public.profiles (lower(email));

-- New auth user -> profile with the default role. security definer so it can write
-- public.profiles from the auth schema trigger; empty search_path avoids hijacking.
create function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles (id, email)
    values (new.id, new.email);
    return new;
end;
$$;

create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- Role check used by RLS policies. security definer so policies on profiles itself
-- can call it without recursing into profiles' own RLS.
create function public.has_role(variadic roles text[])
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1 from public.profiles
        where id = (select auth.uid()) and role = any (roles)
    );
$$;

-- ── Domain tables ───────────────────────────────────────────────────────────

create table public.policies (
    id text primary key,
    source_text text not null,
    rules_json jsonb not null,
    created_by uuid references public.profiles (id) on delete set null,
    created_at timestamptz not null default now()
);

create table public.jds (
    id text primary key,
    source_text text not null,
    requirements_json jsonb not null,
    created_by uuid references public.profiles (id) on delete set null,
    created_at timestamptz not null default now()
);

create table public.students (
    id text primary key,
    name text not null,
    email text,  -- links the record to the student's login (see students RLS)
    branch text not null,
    batch text not null,
    cgpa double precision not null check (cgpa between 0 and 10),
    active_backlogs integer not null check (active_backlogs >= 0),
    is_placed boolean not null default false,
    resume_text text,
    parsed_json jsonb not null,
    resume_path text,  -- object path in the private 'resumes' bucket
    created_by uuid references public.profiles (id) on delete set null,
    created_at timestamptz not null default now()
);

create index students_email_idx on public.students (lower(email));
create index jds_created_by_idx on public.jds (created_by);

-- ── Row-level security ──────────────────────────────────────────────────────

alter table public.profiles enable row level security;
alter table public.policies enable row level security;
alter table public.jds enable row level security;
alter table public.students enable row level security;

-- Nothing here is for anonymous visitors.
revoke all on public.profiles, public.policies, public.jds, public.students from anon;

-- profiles: you see yourself; admins see and change everyone. No self-update policy,
-- so a user cannot change their own role.
create policy "profiles: read own or admin" on public.profiles
    for select to authenticated
    using (id = (select auth.uid()) or public.has_role('admin'));

create policy "profiles: admin updates" on public.profiles
    for update to authenticated
    using (public.has_role('admin'))
    with check (public.has_role('admin'));

-- policies: everyone signed in can read the rules; officers and admins write them.
create policy "policies: read" on public.policies
    for select to authenticated using (true);

create policy "policies: officer/admin write" on public.policies
    for all to authenticated
    using (public.has_role('officer', 'admin'))
    with check (public.has_role('officer', 'admin'));

-- jds: everyone signed in can read drives; officers/admins manage all, recruiters
-- manage only the JDs they created.
create policy "jds: read" on public.jds
    for select to authenticated using (true);

create policy "jds: officer/admin write" on public.jds
    for all to authenticated
    using (public.has_role('officer', 'admin'))
    with check (public.has_role('officer', 'admin'));

create policy "jds: recruiter writes own" on public.jds
    for all to authenticated
    using (public.has_role('recruiter') and created_by = (select auth.uid()))
    with check (public.has_role('recruiter') and created_by = (select auth.uid()));

-- students: officers/admins see and manage all records; a student sees only the record
-- whose email matches their verified login email. Recruiters see nothing yet (students
-- are released to recruiters only by the future staged auto-apply flow).
create policy "students: officer/admin all" on public.students
    for all to authenticated
    using (public.has_role('officer', 'admin'))
    with check (public.has_role('officer', 'admin'));

create policy "students: read own" on public.students
    for select to authenticated
    using (lower(email) = lower((select auth.jwt() ->> 'email')));

-- ── Resume storage ──────────────────────────────────────────────────────────

insert into storage.buckets (id, name, public)
values ('resumes', 'resumes', false)
on conflict (id) do nothing;

-- Read access mirrors the students table. No insert/update/delete policies: only the
-- backend (secret key) writes resumes.
create policy "resumes: officer/admin read" on storage.objects
    for select to authenticated
    using (bucket_id = 'resumes' and public.has_role('officer', 'admin'));

create policy "resumes: student reads own" on storage.objects
    for select to authenticated
    using (
        bucket_id = 'resumes'
        and exists (
            select 1 from public.students s
            where s.resume_path = storage.objects.name
              and lower(s.email) = lower((select auth.jwt() ->> 'email'))
        )
    );
