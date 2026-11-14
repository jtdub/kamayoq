"""Settings of kamayoq, read from KAMAYOQ_ environment variables."""

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
    TomlConfigSettingsSource,
)

ENV_PREFIX = "KAMAYOQ_"
CONFIG_FILE_ENV = "KAMAYOQ_CONFIG_FILE"

LIBPQ_SCHEMES = frozenset({"postgres", "postgresql"})

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class InvalidSettingsError(Exception):
    """Raise when the settings cannot load. The message is safe to print."""


def config_file_path() -> Path | None:
    """Return the resolved path in KAMAYOQ_CONFIG_FILE, or None if it is not set.

    Raises:
        InvalidSettingsError: If the value is empty or does not name a file.
    """
    value = os.environ.get(CONFIG_FILE_ENV)
    if value is None:
        return None
    if not value:
        raise InvalidSettingsError(
            f"{CONFIG_FILE_ENV} is empty. "
            "Unset it, or set it to the path of a TOML file."
        )
    path = Path(value).resolve()
    if not path.is_file():
        raise InvalidSettingsError(
            f"{CONFIG_FILE_ENV} names {path}, which is not a file."
        )
    return path


class Settings(BaseSettings):
    """Validated settings of the kamayoq server.

    Environment variables win over the TOML file in KAMAYOQ_CONFIG_FILE.
    """

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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read the environment, then the TOML file. Do not read a .env file."""
        path = config_file_path()
        if path is None:
            return init_settings, env_settings
        toml_settings = TomlConfigSettingsSource(settings_cls, toml_file=path)
        return init_settings, env_settings, toml_settings

    @field_validator("log_level", mode="before")
    @classmethod
    def upper_case_log_level(cls, value: object) -> object:
        """Accept a log level in any case."""
        return value.upper() if isinstance(value, str) else value

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
    """Return the settings from the environment and the TOML file.

    Raises:
        InvalidSettingsError: If a setting or the TOML file is not valid.
    """
    path = config_file_path()
    try:
        return Settings()
    except ValidationError as error:
        raise InvalidSettingsError(validation_message(error)) from None
    except tomllib.TOMLDecodeError as error:
        raise InvalidSettingsError(f"{path} is not valid TOML: {error}") from None
    except UnicodeDecodeError:
        raise InvalidSettingsError(f"{path} is not UTF-8 text.") from None
    except OSError as error:
        raise InvalidSettingsError(f"cannot read {path}: {error.strerror}") from None
    except SettingsError as error:
        raise InvalidSettingsError(f"Settings are not valid: {error}") from None
