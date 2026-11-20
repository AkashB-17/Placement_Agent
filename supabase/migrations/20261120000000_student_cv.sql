-- Students upload their own CV.
--
-- The placement office creates a student's record with the academic details it holds
-- (branch, batch, CGPA, backlogs, placed status); the student later uploads or replaces
-- their CV. So a record can exist before it has a CV, and the CV can change over time.
--
-- * parsed_json gets an empty default for records without a CV (stays NOT NULL).
-- * resume_updated_at records when the current CV was uploaded (NULL = no CV yet).
--
-- Every uploaded CV is stored under its own content-addressed path in the private
-- 'resumes' bucket and never overwritten, so applications that pinned an earlier
-- version keep pointing at exactly what was scored.

alter table public.students alter column parsed_json set default '{}'::jsonb;
alter table public.students add column if not exists resume_updated_at timestamptz;

-- Existing records already have a CV: date them from when they were created.
update public.students
set resume_updated_at = created_at
where resume_updated_at is null and coalesce(resume_text, '') <> '';
