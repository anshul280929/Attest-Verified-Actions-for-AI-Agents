"""Configuration for the downstream mock orders and payments service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class MockSettings(BaseSettings):
    """Downstream mock server settings and default chaos configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mock_port: int = 8001
    default_fault_profile: str = "none"
    fault_rate: float = 0.3
    default_seed: int = 42
    timeout_delay_seconds: float = 2.5


mock_settings = MockSettings()
