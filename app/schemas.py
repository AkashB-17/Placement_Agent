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
