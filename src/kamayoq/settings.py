"""Settings of kamayoq, read from KAMAYOQ_ environment variables."""

from typing import Literal

from pydantic import Field, PostgresDsn, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "KAMAYOQ_"

LIBPQ_SCHEMES = frozenset({"postgres", "postgresql"})

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class InvalidSettingsError(Exception):
    """Raise when the settings cannot load. The message is safe to print."""


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

    @field_validator("database_url", mode="after")
    @classmethod
    def require_libpq_scheme(cls, value: PostgresDsn) -> PostgresDsn:
        """Reject a driver scheme. The message names the scheme only."""
        if value.scheme not in LIBPQ_SCHEMES:
            raise ValueError(
                f"the scheme must be postgres or postgresql, not {value.scheme}"
            )
        return value


def validation_message(error: ValidationError) -> str:
    """Return one line for each error, with the field and its variable only."""
    lines = ["Settings are not valid:"]
    for detail in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in detail["loc"])
        env_name = ENV_PREFIX + str(detail["loc"][0]).upper()
        lines.append(f"- {location} ({env_name}): {detail['msg']}")
    return "\n".join(lines)


def load_settings() -> Settings:
    """Return the settings from the environment.

    Raises:
        InvalidSettingsError: If a setting is missing or not valid.
    """
    try:
        return Settings()
    except ValidationError as error:
        raise InvalidSettingsError(validation_message(error)) from None
