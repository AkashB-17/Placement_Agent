// Mirrors app/schemas.py. Keep in sync when the API changes.

export type Role = "student" | "officer" | "recruiter" | "admin";

export interface Profile {
  id: string;
  email: string | null;
  role: Role;
}

export interface PolicyRules {
  min_cgpa: number | null;
  max_active_backlogs: number | null;
  allowed_branches: string[];
  allowed_batches: string[];
  max_applications_per_student: number | null;
  placed_student_rules: string[];
  placed_students_can_apply: boolean | null;
}

export interface JDRequirements {
  company: string | null;
  role: string | null;
  required_skills: string[];
  preferred_skills: string[];
  min_cgpa_override: number | null;
  allowed_branches: string[];
  allowed_batches: string[];
  ctc: string | null;
  deadline: string | null;
  experience_required: string | null;
}

export interface ParsedResume {
  skills: string[];
  projects: string[];
  education: string[];
  experience: string[];
}

export interface PolicySummary {
  id: string;
  min_cgpa: number | null;
  max_active_backlogs: number | null;
  allowed_branches: string[];
  allowed_batches: string[];
  placed_students_can_apply: boolean | null;
}

export interface JDSummary {
  id: string;
  company: string | null;
  role: string | null;
  required_skills: string[];
  allowed_branches: string[];
  deadline: string | null;
  deadline_at: string | null;
  /** The JD's own deadline, when it has been changed. */
  original_deadline: string | null;
  deadline_changed_at: string | null;
  can_edit_deadline: boolean;
  posted_at: string | null;
  /** When an admin last edited the job's details. */
  edited_at: string | null;
}

export interface DeadlineChange {
  jd_id: string;
  deadline: string;
  deadline_at: string;
  previous_deadline: string | null;
  /** Pending applications moved earlier to fit the new deadline. */
  rescheduled: number;
}

export interface JDDetail {
  id: string;
  requirements: JDRequirements;
  source_text: string;
  original_deadline: string | null;
  deadline_changed_at: string | null;
  edited_at: string | null;
}

export interface StudentSummary {
  id: string;
  name: string;
  email: string | null;
  branch: string;
  batch: string;
  cgpa: number;
  active_backlogs: number;
  is_placed: boolean;
  has_resume: boolean;
}

export interface StudentProfile {
  name: string;
  email: string | null;
  branch: string;
  batch: string;
  cgpa: number;
  active_backlogs: number;
  is_placed: boolean;
}

export interface StudentDetail {
  id: string;
  profile: StudentProfile;
  parsed_resume: ParsedResume;
  resume_text: string;
  /** A CV has been uploaded (students upload their own). */
  has_resume: boolean;
  has_resume_file: boolean;
  resume_updated_at: string | null;
}

export interface IngestResponse {
  id: string;
  warnings?: string[];
  /** JD uploads: auto-apply started in the background (null when switched off). */
  auto_apply?: string | null;
}

export interface FailedRule {
  rule: string;
  source: "policy" | "jd";
  description: string;
  student_value: unknown;
  required_value: unknown;
}

export interface SkillQuote {
  skill: string;
  quote: string;
}

export interface ScoreBreakdown {
  score: number | null;
  matched_required: string[];
  missing_required: string[];
  matched_preferred: string[];
  missing_preferred: string[];
  evidence: SkillQuote[];
}

export interface Citation {
  rule: string;
  source: "policy" | "jd";
  source_id: string;
  chunks: { text: string; distance: number }[];
}

export interface MatchResult {
  student_id: string;
  student_name: string;
  eligibility: { eligible: boolean; failed_rules: FailedRule[] };
  score_breakdown: ScoreBreakdown | null;
  auto_apply_recommended: boolean;
  citations: Citation[];
  /** "cache" = stored verified score, "fresh" = new AI call, "none" = JD has no required skills. */
  score_source?: "cache" | "fresh" | "none" | "no_resume" | null;
}

export interface RankedResponse {
  jd_id: string;
  policy_id: string;
  auto_apply_threshold: number;
  eligible: MatchResult[];
  ineligible: MatchResult[];
  ai_calls: number;
  cached_scores: number;
}

// ── Staged auto-apply ────────────────────────────────────────────────────────

export type ApplicationStatus = "pending" | "withdrawn" | "submitted";
/** manual: the student applied from their job board; auto: an auto-apply run. */
export type ApplicationSource = "auto" | "manual";

export interface AutoApplyPreferences {
  enabled: boolean;
  min_score: number;
  excluded_companies: string[];
}

export interface PreferencesOut extends AutoApplyPreferences {
  threshold: number;
  withdraw_hours: number;
}

export interface Application {
  id: string;
  student_id: string;
  student_name: string;
  jd_id: string;
  company: string | null;
  role: string | null;
  policy_id: string;
  status: ApplicationStatus;
  score: number;
  score_breakdown: ScoreBreakdown;
  created_at: string;
  release_at: string;
  decided_at: string | null;
  can_withdraw: boolean;
  has_resume_file: boolean;
  source: ApplicationSource;
  /** Why this candidate stands out: built by code from the verified score and academic record. */
  highlights: string[];
}

export interface SkippedStudent {
  student_id: string;
  student_name: string;
  reason: string;
}

export interface AutoApplyRun {
  jd_id: string;
  policy_id: string;
  deadline: string | null;
  release_cutoff: string | null;
  release_at: string;
  created: Application[];
  skipped: SkippedStudent[];
  not_opted_in: number;
}

export interface Notification {
  id: string;
  application_id: string | null;
  kind: "application_pending" | "application_submitted" | "application_withdrawn";
  message: string;
  created_at: string;
  read: boolean;
}

// ── Student job board (GET /me/jobs) ─────────────────────────────────────────

export interface MyJobApplication {
  id: string;
  status: ApplicationStatus;
  release_at: string;
  can_withdraw: boolean;
  source: ApplicationSource;
}

export interface MyJob {
  id: string;
  company: string | null;
  role: string | null;
  ctc: string | null;
  deadline: string | null;
  deadline_at: string | null;
  posted_at: string | null;
  closed: boolean;
  deadline_changed_at: string | null;
  eligibility: { eligible: boolean; failed_rules: FailedRule[] };
  application: MyJobApplication | null;
}

export interface MyJobsResponse {
  policy_id: string | null;
  jobs: MyJob[];
}

// ── CV tips (POST /me/jobs/{id}/cv-tips) ─────────────────────────────────────

export interface CvTip {
  skill: string;
  required: boolean;
  /** surface: the CV shows related work (verified quote); build: the skill needs gaining first. */
  kind: "surface" | "build";
  related_quote: string | null;
  suggestion: string;
}

export interface CvTipsResponse {
  jd_id: string;
  score: number | null;
  tips: CvTip[];
  source: "cache" | "fresh" | "none";
}

// ── College-wide settings (GET/PUT /admin/settings) ──────────────────────────

export interface AppSettings {
  auto_apply_threshold: number;
  /** Used until an admin sets one (AUTO_APPLY_THRESHOLD on the API). */
  default_auto_apply_threshold: number;
  updated_at: string | null;
}
