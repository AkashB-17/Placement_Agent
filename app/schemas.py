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
    branch: str
    batch: str
    cgpa: float
    active_backlogs: int
    is_placed: bool = False
    parsed_resume: ParsedResume | None = None


class PolicyIngestResponse(BaseModel):
    id: str
    rules: PolicyRules


class JDIngestResponse(BaseModel):
    id: str
    requirements: JDRequirements


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
    branch: str
    batch: str
    cgpa: float
    active_backlogs: int
    is_placed: bool


class StudentDetail(BaseModel):
    id: str
    profile: StudentProfile
    parsed_resume: ParsedResume
    resume_text: str


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


class RankedResponse(BaseModel):
    jd_id: str
    policy_id: str
    auto_apply_threshold: float
    eligible: list[MatchResult]
    ineligible: list[MatchResult]
