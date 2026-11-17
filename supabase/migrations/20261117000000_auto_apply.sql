-- Staged auto-apply.
--
-- A student opts in (auto_apply_preferences). When an officer runs auto-apply for a JD,
-- each opted-in student who is eligible and scores at or above their bar gets a PENDING
-- application, pinned to the resume version and score evidence of that moment, and a
-- notification. The student can withdraw until release_at; then the application becomes
-- SUBMITTED and only then is it visible to the JD's recruiter.
--
--   pending --(student withdraws before release_at)--> withdrawn   (final)
--   pending --(release_at passes; backend sweep)-----> submitted   (final)
--
-- release_at = min(created_at + 24 h, JD deadline - buffer), computed by the backend.
-- All writes go through the backend (secret key). RLS below only grants reads, for the
-- web app and as defence in depth.

create table public.auto_apply_preferences (
    student_id text primary key references public.students (id) on delete cascade,
    enabled boolean not null default false,
    min_score real not null check (min_score between 0 and 100),
    excluded_companies jsonb not null default '[]'::jsonb,
    updated_at timestamptz not null default now()
);

create table public.applications (
    id text primary key,
    student_id text not null references public.students (id) on delete cascade,
    jd_id text not null references public.jds (id) on delete cascade,
    policy_id text not null references public.policies (id),
    status text not null default 'pending' check (status in ('pending', 'withdrawn', 'submitted')),
    score real not null,
    match_json jsonb not null,          -- score breakdown + evidence that justified applying
    resume_path text,                   -- pinned, content-addressed object in 'resumes'
    resume_sha text not null,           -- hash of the resume text that was scored
    created_at timestamptz not null default now(),
    release_at timestamptz not null,
    decided_at timestamptz,             -- when it was withdrawn or submitted
    created_by uuid references auth.users (id) on delete set null,
    -- One application per student per JD, ever: a withdrawal is respected, not retried.
    unique (student_id, jd_id),
    check (release_at > created_at),
    check ((status = 'pending') = (decided_at is null))
);

-- The release sweep scans pending applications by release time.
create index applications_pending_release_idx on public.applications (release_at) where status = 'pending';
create index applications_jd_idx on public.applications (jd_id);

create table public.notifications (
    id text primary key,
    student_id text not null references public.students (id) on delete cascade,
    application_id text references public.applications (id) on delete cascade,
    kind text not null check (kind in ('application_pending', 'application_submitted', 'application_withdrawn')),
    message text not null,
    created_at timestamptz not null default now(),
    read_at timestamptz
);

create index notifications_student_idx on public.notifications (student_id, created_at desc);

-- ── Row-level security ──────────────────────────────────────────────────────

alter table public.auto_apply_preferences enable row level security;
alter table public.applications enable row level security;
alter table public.notifications enable row level security;

revoke all on public.auto_apply_preferences, public.applications, public.notifications from anon;

-- "Own" means: the student record whose email matches the verified login email.
create policy "preferences: officer/admin read" on public.auto_apply_preferences
    for select to authenticated
    using (public.has_role('officer', 'admin'));

create policy "preferences: student reads own" on public.auto_apply_preferences
    for select to authenticated
    using (exists (
        select 1 from public.students s
        where s.id = auto_apply_preferences.student_id
          and lower(s.email) = lower((select auth.jwt() ->> 'email'))
    ));

create policy "applications: officer/admin read" on public.applications
    for select to authenticated
    using (public.has_role('officer', 'admin'));

create policy "applications: student reads own" on public.applications
    for select to authenticated
    using (exists (
        select 1 from public.students s
        where s.id = applications.student_id
          and lower(s.email) = lower((select auth.jwt() ->> 'email'))
    ));

-- Recruiters see an application only once it is released, and only for their own JDs.
create policy "applications: recruiter reads submitted for own JDs" on public.applications
    for select to authenticated
    using (
        status = 'submitted'
        and public.has_role('recruiter')
        and exists (select 1 from public.jds j where j.id = applications.jd_id and j.created_by = (select auth.uid()))
    );

create policy "notifications: student reads own" on public.notifications
    for select to authenticated
    using (exists (
        select 1 from public.students s
        where s.id = notifications.student_id
          and lower(s.email) = lower((select auth.jwt() ->> 'email'))
    ));

-- A recruiter may open the pinned resume of a submitted application to their JD.
create policy "resumes: recruiter reads submitted applications" on storage.objects
    for select to authenticated
    using (
        bucket_id = 'resumes'
        and public.has_role('recruiter')
        and exists (
            select 1 from public.applications a
            join public.jds j on j.id = a.jd_id
            where a.resume_path = storage.objects.name
              and a.status = 'submitted'
              and j.created_by = (select auth.uid())
        )
    );
