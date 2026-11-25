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


class StudentUpdate(BaseModel):
    """The office's edit of a student's academic record (the CV is the student's)."""
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(None, max_length=320, description="Login email; links the record to the student's account")
    branch: str = Field(min_length=1, max_length=100)
    batch: str = Field(min_length=1, max_length=20)
    cgpa: float = Field(ge=0, le=10)
    active_backlogs: int = Field(ge=0, le=100)
    is_placed: bool = False


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
    deadline: str | None = None
    deadline_at: datetime | None = None
    original_deadline: str | None = Field(None, description="The JD's own deadline, when it was changed")
    deadline_changed_at: datetime | None = None
    can_edit_deadline: bool = False
    posted_at: datetime | None = None
    edited_at: datetime | None = Field(None, description="When an admin last edited the job's details")


class DeadlineUpdate(BaseModel):
    deadline: str = Field(
        min_length=8, max_length=40,
        description="A date (2026-12-05: the end of that day, college time) or date and time (2026-12-05T17:00)",
    )


class DeadlineChange(BaseModel):
    jd_id: str
    deadline: str
    deadline_at: datetime
    previous_deadline: str | None
    rescheduled: int = Field(description="Pending applications moved earlier to fit the new deadline")


class JDDetail(BaseModel):
    id: str
    requirements: JDRequirements
    source_text: str
    original_deadline: str | None = Field(None, description="The JD's own deadline, when it was changed")
    deadline_changed_at: datetime | None = None
    edited_at: datetime | None = Field(None, description="When an admin last edited the job's details")


class JDEdit(BaseModel):
    """An admin's edit of a job. Replaces the details extracted from the JD text (which are
    kept); the posted text itself is not changed."""
    company: str | None = Field(None, max_length=200)
    role: str | None = Field(None, max_length=200)
    required_skills: list[str] = Field(default_factory=list, max_length=50)
    preferred_skills: list[str] = Field(default_factory=list, max_length=50)
    min_cgpa_override: float | None = Field(None, ge=0, le=10)
    allowed_branches: list[str] = Field(default_factory=list, max_length=30)
    allowed_batches: list[str] = Field(default_factory=list, max_length=10)
    ctc: str | None = Field(None, max_length=200)
    deadline: str | None = Field(None, max_length=40, description="Changing it reschedules pending applications")
    experience_required: str | None = Field(None, max_length=200)


class JDDeleted(BaseModel):
    id: str
    applications_removed: int
    students_notified: int


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
ApplicationSource = Literal["auto", "manual"]


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
    source: ApplicationSource = Field(description="manual: the student applied; auto: an auto-apply run")
    highlights: list[str] = Field(
        default_factory=list,
        description="Why this candidate stands out: built by code from the verified score and academic record",
    )


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
    source: ApplicationSource


class MyJob(BaseModel):
    id: str
    company: str | None
    role: str | None
    ctc: str | None
    deadline: str | None = Field(description="As written in the JD")
    deadline_at: datetime | None = Field(description="Parsed by code; null if unrecognised (e.g. rolling)")
    posted_at: datetime | None
    closed: bool
    deadline_changed_at: datetime | None = None
    eligibility: EligibilityResult
    application: MyJobApplication | None


class MyJobsResponse(BaseModel):
    policy_id: str | None = Field(description="Policy eligibility was checked against; null if none exists")
    jobs: list[MyJob]


class CvTip(BaseModel):
    skill: str
    required: bool = Field(description="Required by the JD (else preferred)")
    kind: Literal["surface", "build"] = Field(
        description="surface: the CV shows related work (related_quote, verified by code) that could be "
        "written to show this skill; build: no related evidence, the student needs to gain it first"
    )
    related_quote: str | None = None
    suggestion: str


class CvTipsResponse(BaseModel):
    jd_id: str
    score: float | None
    tips: list[CvTip]
    source: Literal["cache", "fresh", "none"] = Field(description="none: nothing missing, no AI call")
