-- Recruiters (for their own jobs) and the placement office can change a job's deadline.
--
-- The deadline extracted from the JD text stays in requirements_json untouched, so the
-- original is never lost and re-uploading the same JD text can't silently undo a change.
-- deadline_override, when set, is the deadline the app uses everywhere (eligibility of
-- applications, release times, the student job board).
--
-- Shortening a deadline moves pending applications' release time earlier (in the API, in
-- one transaction with this update) and notifies each affected student.

alter table public.jds add column if not exists deadline_override text;
alter table public.jds add column if not exists deadline_changed_at timestamptz;
alter table public.jds add column if not exists deadline_changed_by uuid references auth.users (id) on delete set null;
