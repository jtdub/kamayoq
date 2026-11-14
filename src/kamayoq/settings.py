"""Settings of kamayoq, read from KAMAYOQ_ environment variables."""

from typing import Literal

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "KAMAYOQ_"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Validated settings of the kamayoq server."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        extra="forbid",
        hide_input_in_errors=True,
        frozen=True,
    )

    database_url: PostgresDsn = Field(repr=False)
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    readiness_timeout: float = Field(default=2.0, gt=0)
    log_level: LogLevel = "INFO"
    api_docs: bool = False


def load_settings() -> Settings:
    """Return the settings from the environment."""
    return Settings()
