from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


def _normalize_pg_url(url: str) -> str:
    """Normalize postgresql:// URLs to use the psycopg v3 driver."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


class Settings(BaseSettings):
    """Application settings loaded from the project root .env file."""

    environment: str = "development"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/fin_intel"
    test_database_url: str = "postgresql://postgres:postgres@localhost:5432/fin_intel_test"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 48
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    advisor_timeout_seconds: int = 25
    advisor_rate_limit_per_min: int = 10
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlalchemy_database_url(self) -> str:
        return _normalize_pg_url(self.database_url)

    @property
    def sqlalchemy_test_database_url(self) -> str:
        return _normalize_pg_url(self.test_database_url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_dev(self) -> bool:
        return self.environment.strip().lower() in {"dev", "development", "local"}


settings = Settings()
