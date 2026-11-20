from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PolicyRules(BaseModel):
    min_cgpa: float | None = None
    max_active_backlogs: int | None = None
    allowed_branches: list[str] = Field(default_factory=list)
    allowed_batches: list[str] = Field(default_factory=list)
    max_applications_per_student: int | None = None
    placed_student_rules: list[str] = Field(default_factory=list)
    # Part B: None = "not stated"; False = explicitly forbidden
    placed_students_can_apply: bool | None = None


class JDRequirements(BaseModel):
    company: str | None = None
    role: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    min_cgpa_override: float | None = None
    allowed_branches: list[str] = Field(default_factory=list)
    allowed_batches: list[str] = Field(default_factory=list)
    ctc: str | None = None
    deadline: str | None = None
    experience_required: str | None = None


class ParsedResume(BaseModel):
    skills: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)


class StudentProfile(BaseModel):
    name: str
    email: str | None = None
    branch: str
    batch: str
    cgpa: float
    active_backlogs: int
    is_placed: bool = False
    parsed_resume: ParsedResume | None = None


class PolicyIngestResponse(BaseModel):
    id: str
    rules: PolicyRules
    warnings: list[str] = Field(default_factory=list)


class JDIngestResponse(BaseModel):
    id: str
    requirements: JDRequirements
    warnings: list[str] = Field(default_factory=list)


class StudentIngestResponse(BaseModel):
    id: str
    profile: StudentProfile
    parsed_resume: ParsedResume


# ── List / GET responses ────────────────────────────────────────────────────

class PolicySummary(BaseModel):
    id: str
    min_cgpa: float | None
    max_active_backlogs: int | None
    allowed_branches: list[str]
    allowed_batches: list[str]
    placed_students_can_apply: bool | None


class PolicyDetail(BaseModel):
    id: str
    rules: PolicyRules
    source_text: str


class JDSummary(BaseModel):
    id: str
    company: str | None
    role: str | None
    required_skills: list[str]
    allowed_branches: list[str]


class JDDetail(BaseModel):
    id: str
    requirements: JDRequirements
    source_text: str


class StudentSummary(BaseModel):
    id: str
    name: str
    email: str | None = None
    branch: str
    batch: str
    cgpa: float
    active_backlogs: int
    is_placed: bool
    has_resume: bool = False


class StudentDetail(BaseModel):
    id: str
    profile: StudentProfile
    parsed_resume: ParsedResume
    resume_text: str
    has_resume: bool = False  # a CV has been uploaded (text extracted)
    has_resume_file: bool = False  # the original file is in storage (Supabase only)
    resume_updated_at: datetime | None = None


class ResumeLink(BaseModel):
    url: str
    expires_in: int


# ── Admin ───────────────────────────────────────────────────────────────────

Role = Literal["student", "officer", "recruiter", "admin"]


class InviteRequest(BaseModel):
    email: str
    role: Role


class RoleUpdate(BaseModel):
    role: Role


class ProfileOut(BaseModel):
    id: str
    email: str | None
    role: Role


# ── Eligibility / scoring / match ───────────────────────────────────────────

RuleSource = Literal["policy", "jd"]


class FailedRule(BaseModel):
    rule: str
    source: RuleSource
    description: str
    student_value: Any
    required_value: Any


class EligibilityResult(BaseModel):
    eligible: bool
    failed_rules: list[FailedRule] = Field(default_factory=list)


class SkillQuote(BaseModel):
    skill: str
    quote: str


class ScoreBreakdown(BaseModel):
    score: float | None
    matched_required: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    matched_preferred: list[str] = Field(default_factory=list)
    missing_preferred: list[str] = Field(default_factory=list)
    evidence: list[SkillQuote] = Field(default_factory=list)


class CitationChunk(BaseModel):
    text: str
    distance: float


class Citation(BaseModel):
    rule: str
    source: RuleSource
    source_id: str
    chunks: list[CitationChunk] = Field(default_factory=list)


class MatchRequest(BaseModel):
    jd_id: str
    student_id: str
    policy_id: str


class MatchResult(BaseModel):
    student_id: str
    student_name: str
    eligibility: EligibilityResult
    score_breakdown: ScoreBreakdown | None
    auto_apply_recommended: bool
    citations: list[Citation] = Field(default_factory=list)
    # Where the score came from: "cache" (stored verified result), "fresh" (new AI call),
    # "none" (JD has no required skills, nothing to call). None when not scored (ineligible).
    # "no_resume": eligible but no CV uploaded yet, so there is nothing to score.
    score_source: Literal["cache", "fresh", "none", "no_resume"] | None = None


class RankedResponse(BaseModel):
    jd_id: str
    policy_id: str
    auto_apply_threshold: float
    eligible: list[MatchResult]
    ineligible: list[MatchResult]
    ai_calls: int = Field(0, description="Scores computed by a new AI call in this request")
    cached_scores: int = Field(0, description="Scores served from the score cache")


# ── Staged auto-apply ───────────────────────────────────────────────────────

ApplicationStatus = Literal["pending", "withdrawn", "submitted"]


class AutoApplyPreferences(BaseModel):
    enabled: bool = False
    min_score: float = Field(ge=0, le=100, description="Only apply when the score is at least this")
    excluded_companies: list[str] = Field(default_factory=list, max_length=50)


class PreferencesOut(AutoApplyPreferences):
    threshold: float = Field(description="College-wide minimum; min_score can't be lower")
    withdraw_hours: float


class ApplicationOut(BaseModel):
    id: str
    student_id: str
    student_name: str
    jd_id: str
    company: str | None
    role: str | None
    policy_id: str
    status: ApplicationStatus
    score: float
    score_breakdown: ScoreBreakdown
    created_at: datetime
    release_at: datetime
    decided_at: datetime | None
    can_withdraw: bool
    has_resume_file: bool


class SkippedStudent(BaseModel):
    student_id: str
    student_name: str
    reason: str


class AutoApplyRun(BaseModel):
    jd_id: str
    policy_id: str
    deadline: datetime | None
    release_cutoff: datetime | None = Field(description="Deadline minus buffer; releases never happen later")
    release_at: datetime
    created: list[ApplicationOut]
    skipped: list[SkippedStudent]
    not_opted_in: int


class NotificationOut(BaseModel):
    id: str
    application_id: str | None
    kind: str
    message: str
    created_at: datetime
    read: bool


# ── Student job board ───────────────────────────────────────────────────────

class MyJobApplication(BaseModel):
    id: str
    status: ApplicationStatus
    release_at: datetime
    can_withdraw: bool


class MyJob(BaseModel):
    id: str
    company: str | None
    role: str | None
    ctc: str | None
    deadline: str | None = Field(description="As written in the JD")
    deadline_at: datetime | None = Field(description="Parsed by code; null if unrecognised (e.g. rolling)")
    posted_at: datetime | None
    closed: bool
    eligibility: EligibilityResult
    application: MyJobApplication | None


class MyJobsResponse(BaseModel):
    policy_id: str | None = Field(description="Policy eligibility was checked against; null if none exists")
    jobs: list[MyJob]
