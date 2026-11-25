-- Admins can edit a job's details (company, role, skills, eligibility rules, CTC, ...) and
-- remove a job.
--
-- The requirements extracted from the JD text stay in requirements_json untouched;
-- requirements_edited, when set, is the version the app uses (eligibility, scoring,
-- job board). Re-uploading the same JD text re-extracts requirements_json but never
-- overwrites an admin's edit. A changed deadline still lives in deadline_override.
--
-- Removing a job deletes its applications (and their notifications) and cached scores
-- in the API, in one transaction; affected students are notified.

alter table public.jds add column if not exists requirements_edited jsonb;
alter table public.jds add column if not exists edited_at timestamptz;
alter table public.jds add column if not exists edited_by uuid references auth.users (id) on delete set null;
