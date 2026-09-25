"""Configuration settings for the Attest gateway service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://attest:attest_dev@localhost:5432/attest"
    downstream_base_url: str = "http://localhost:8001"
    app_env: str = "development"
    log_level: str = "INFO"
    default_timeout_seconds: float = 2.0
    max_retry_attempts: int = 3


settings = Settings()
