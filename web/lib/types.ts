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
}

export interface JDDetail {
  id: string;
  requirements: JDRequirements;
  source_text: string;
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
  has_resume_file: boolean;
}

export interface IngestResponse {
  id: string;
  warnings?: string[];
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
}

export interface RankedResponse {
  jd_id: string;
  policy_id: string;
  auto_apply_threshold: number;
  eligible: MatchResult[];
  ineligible: MatchResult[];
}
