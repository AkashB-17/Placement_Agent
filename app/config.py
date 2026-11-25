from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    openai_api_key: str = Field(default="")
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    sqlite_path: Path = Path("./data/placement.db")
    chroma_path: Path = Path("./.chroma")
    auto_apply_threshold: float = 80.0
    # Run auto-apply in the background whenever a JD is uploaded (against the newest policy).
    auto_apply_on_upload: bool = True

    # Staged auto-apply: a pending application is sent at the earlier of
    # (created + withdraw window) and (JD deadline - buffer).
    auto_apply_withdraw_hours: float = 24.0
    auto_apply_deadline_buffer_hours: float = 6.0
    auto_apply_min_window_minutes: float = 60.0  # refuse a run that would leave less time to withdraw
    # A student's own application near the deadline: if the normal window doesn't fit, it is
    # sent this long before the deadline instead; inside this period it is sent at once.
    # Manual applications are accepted until the deadline itself.
    manual_apply_last_call_minutes: float = 10.0
    deadline_utc_offset_minutes: int = 330  # a date-only JD deadline runs to 23:59:59.999999 here (IST)
    release_sweep_seconds: float = 60.0  # background release interval; 0 disables (tests)

    # Re-embed policies/JDs missing from the vector index at startup (hosted disks are
    # often wiped on deploy; Postgres holds the source text).
    index_sync_on_startup: bool = True

    # Supabase. When database_url is set, Postgres replaces SQLite.
    supabase_url: str = ""  # https://<project-ref>.supabase.co
    supabase_publishable_key: str = ""  # sb_publishable_... (safe for clients; used to log in)
    supabase_secret_key: str = ""  # sb_secret_... (server only; bypasses RLS)
    database_url: str = ""  # Session pooler connection string
    resume_bucket: str = "resumes"
    signed_url_ttl_seconds: int = 60

    # Local-only escape hatch so the SQLite demo runs without Supabase. Every request is
    # treated as an admin. Refused at startup when database_url is set.
    dev_auth_bypass: bool = False

    # Browser origins allowed to call the API (the Next.js app). JSON list in .env.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("supabase_url")
    @classmethod
    def _project_url_only(cls, value: str) -> str:
        """Accept the dashboard's Data API URL too: keep only https://<ref>.supabase.co."""
        value = value.strip().rstrip("/")
        for suffix in ("/rest/v1", "/auth/v1", "/storage/v1"):
            if value.endswith(suffix):
                value = value[: -len(suffix)]
        return value


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def set_settings(settings: Settings) -> None:
    global _settings
    _settings = settings


def reset_settings() -> None:
    global _settings
    _settings = None
