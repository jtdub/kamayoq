"""Settings of kamayoq, read from KAMAYOQ_ environment variables."""

import os
import re
import tomllib
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    Field,
    PostgresDsn,
    ValidationError,
    ValidationInfo,
    field_validator,
)
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
    TomlConfigSettingsSource,
)

ENV_PREFIX = "KAMAYOQ_"
CONFIG_FILE_ENV = "KAMAYOQ_CONFIG_FILE"
LIBPQ_SCHEMES = frozenset({"postgres", "postgresql"})
PLUGIN_REFERENCE = re.compile(r"[a-z][a-z0-9_]*:[A-Za-z0-9][A-Za-z0-9._-]*")
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
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


def require_secure_url(value: str) -> str:
    """Return the URL unchanged if it is https, or http on a loopback host.

    Raises:
        ValueError: If the URL is empty, has white space, user info, a query, a
            fragment, or no host, or uses another scheme.
    """
    if not value or any(character.isspace() for character in value):
        raise ValueError("the URL must not be empty or contain white space")
    if "?" in value or "#" in value:
        raise ValueError("the URL must not have a query or a fragment")
    parts = urlsplit(value)
    if "@" in parts.netloc:
        raise ValueError("the URL must not have user info")
    if not parts.hostname:
        raise ValueError("the URL must have a host")
    is_loopback_http = parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS
    if parts.scheme != "https" and not is_loopback_http:
        raise ValueError(
            "the URL must use https, or http on localhost, 127.0.0.1, or [::1]"
        )
    return value


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
    plugins: Annotated[frozenset[str], NoDecode] = frozenset()
    oidc_issuer: str | None = None
    oidc_audience: str | None = Field(default=None, min_length=1, validate_default=True)
    oidc_groups_claim: str = Field(default="groups", min_length=1)
    secrets_backend: Literal["env", "file"] = "env"
    secrets_dir: Path = Field(default=Path("/run/secrets"), validate_default=True)

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

    @field_validator("plugins", mode="before")
    @classmethod
    def split_plugin_list(cls, value: object) -> object:
        """Split a comma list into stripped entries. Keep a list as it is."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",")]
        return value

    @field_validator("plugins", mode="after")
    @classmethod
    def check_plugin_references(cls, value: frozenset[str]) -> frozenset[str]:
        """Reject each entry that is not group:name."""
        bad = sorted(item for item in value if not PLUGIN_REFERENCE.fullmatch(item))
        if bad:
            raise ValueError(
                "each entry must be group:name, for example runtimes:langgraph. "
                f"Not valid: {', '.join(repr(item) for item in bad)}"
            )
        return value

    @field_validator("oidc_issuer", mode="after")
    @classmethod
    def require_secure_issuer(cls, value: str | None) -> str | None:
        """Reject an issuer that is not https or a loopback http URL."""
        return value if value is None else require_secure_url(value)

    @field_validator("oidc_audience", mode="after")
    @classmethod
    def require_issuer_with_audience(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        """Reject one of the issuer and the audience without the other.

        An issuer that failed its own check is not in the data, so it gives no
        second error here.
        """
        if "oidc_issuer" not in info.data:
            return value
        if (info.data["oidc_issuer"] is None) != (value is None):
            raise ValueError(
                f"set both {ENV_PREFIX}OIDC_ISSUER and {ENV_PREFIX}OIDC_AUDIENCE, "
                "or neither"
            )
        return value

    @field_validator("secrets_dir", mode="before")
    @classmethod
    def reject_empty_secrets_dir(cls, value: object) -> object:
        """Reject an empty path. It does not become the current directory."""
        if value == "":
            raise ValueError("must not be empty")
        return value

    @field_validator("secrets_dir", mode="after")
    @classmethod
    def require_secrets_dir(cls, value: Path, info: ValidationInfo) -> Path:
        """Require a directory for the file backend. The message has no path."""
        if info.data.get("secrets_backend") == "file" and not value.is_dir():
            raise ValueError("must be a directory when secrets_backend is file")
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def require_libpq_scheme(cls, value: PostgresDsn) -> PostgresDsn:
        """Reject a driver scheme. The message names the scheme only."""
        if value.scheme not in LIBPQ_SCHEMES:
            raise ValueError(
                f"the scheme must be postgres or postgresql, not {value.scheme}"
            )
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def require_one_host(cls, value: PostgresDsn) -> PostgresDsn:
        """Reject a URL with more than one host. The message has no URL."""
        if len(value.hosts()) > 1:
            raise ValueError("kamayoq supports one database host only")
        return value


def validation_message(error: ValidationError) -> str:
    """Return one line for each error. An unknown key names no variable."""
    lines = ["Settings are not valid:"]
    for detail in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in detail["loc"])
        source = f" ({ENV_PREFIX}{str(detail['loc'][0]).upper()})"
        if detail["type"] == "extra_forbidden":
            source = ""
        lines.append(f"- {location}{source}: {detail['msg']}")
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
