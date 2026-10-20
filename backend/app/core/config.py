"""Environment-based application settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Settings loaded from environment variables or a local .env file."""

    api_version: str = "0.1.0"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    database_url: str | None = None
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = None
    supabase_jwt_audience: str = "authenticated"
    code_execution_enabled: bool = False
    code_runner_image: str = "codeproof-runner:local"
    code_runner_timeout_seconds: int = 8
    code_runner_max_cases: int = 20
    code_runner_max_concurrency: int = 2
    ai_provider: str = "openai"
    ai_model: str = "gpt-5-mini"
    openai_api_key: str | None = None
    ai_timeout_seconds: int = 30
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout_seconds: int = 25

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
