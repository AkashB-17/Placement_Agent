from pydantic import BaseModel, Field


class PolicyRules(BaseModel):
    min_cgpa: float | None = None
    max_active_backlogs: int | None = None
    allowed_branches: list[str] = Field(default_factory=list)
    allowed_batches: list[str] = Field(default_factory=list)
    max_applications_per_student: int | None = None
    placed_student_rules: list[str] = Field(default_factory=list)


class JDRequirements(BaseModel):
    company: str | None = None
    role: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    min_cgpa_override: float | None = None
    allowed_branches: list[str] = Field(default_factory=list)
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
