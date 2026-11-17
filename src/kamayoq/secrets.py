"""Read secrets by name, and keep their values out of log lines."""

import logging
import os
import re
import stat
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from pydantic import SecretStr

from kamayoq.settings import ENV_PREFIX, Settings

SECRET_SCHEME = "secret://"
SECRET_NAME = re.compile(r"[a-z][a-z0-9_]{0,127}")
ENV_SECRET_PREFIX = ENV_PREFIX + "SECRET_"
MAX_SECRET_FILE_BYTES = 64 * 1024
MASK = "**********"
MIN_REDACTED_LENGTH = 4

_logger = logging.getLogger(__name__)
_known_values: set[str] = set()
_known_values_lock = threading.Lock()


def remember(value: str, source: str) -> None:
    """Make the value a known value, so that redact hides it.

    A value shorter than MIN_REDACTED_LENGTH, or of white space only, is not added.
    kamayoq writes one WARNING line that names the source and shows no value.

    Args:
        value: The secret value.
        source: The text that names the value in the warning, for example
            ``secret://slack_token``.
    """
    if len(value) < MIN_REDACTED_LENGTH or value.isspace():
        _logger.warning(
            "%s is shorter than %d characters or is only white space, "
            "so log lines do not hide it",
            source,
            MIN_REDACTED_LENGTH,
        )
        return
    with _known_values_lock:
        _known_values.add(value)


def forget_all() -> None:
    """Remove all known values."""
    with _known_values_lock:
        _known_values.clear()


def _match_spans(text: str, value: str) -> list[tuple[int, int]]:
    """Return the start and end of each match of the value, overlaps included."""
    spans = []
    start = text.find(value)
    while start != -1:
        spans.append((start, start + len(value)))
        start = text.find(value, start + 1)
    return spans


def redact(text: str) -> str:
    """Return the text with each known value replaced by MASK.

    Matches that overlap or touch become one MASK, so no part of a value stays.
    """
    with _known_values_lock:
        values = tuple(_known_values)
    spans = sorted(span for value in values for span in _match_spans(text, value))
    if not spans:
        return text
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    parts = []
    position = 0
    for start, end in merged:
        parts.append(text[position:start] + MASK)
        position = end
    parts.append(text[position:])
    return "".join(parts)


class SecretNotFoundError(Exception):
    """Raise when a secret cannot be read. The message is safe to print.

    The message names the reference and the path. It shows no value and no file
    content.
    """


def check_name(name: str) -> None:
    """Raise SecretNotFoundError if the secret name is not valid."""
    if SECRET_NAME.fullmatch(name) is None:
        raise SecretNotFoundError(
            "the secret name is not valid. A name has lower-case letters, digits, "
            "and _, starts with a letter, and has at most 128 characters"
        )


def parse_reference(reference: str) -> str:
    """Return the secret name of a secret://<name> reference.

    Raises:
        SecretNotFoundError: If the reference or the name is not valid. The message
            does not show the text.
    """
    if not reference.startswith(SECRET_SCHEME):
        raise SecretNotFoundError(f"a secret reference must start with {SECRET_SCHEME}")
    name = reference.removeprefix(SECRET_SCHEME)
    check_name(name)
    return name


class SecretStore(Protocol):
    """A source of secret values, by secret name."""

    async def get(self, name: str) -> SecretStr:
        """Return the value of the secret.

        Raises:
            SecretNotFoundError: If the secret is missing or empty, or the name is
                not valid.
        """
        ...


async def resolve(store: SecretStore, reference: str) -> SecretStr:
    """Return the value of a secret://<name> reference from the store."""
    return await store.get(parse_reference(reference))


def _known_secret(value: str, reference: str) -> SecretStr:
    """Return a non-empty value as a SecretStr, and make it a known value.

    Raises:
        SecretNotFoundError: If the value is empty.
    """
    if not value:
        raise SecretNotFoundError(f"{reference} is empty")
    remember(value, reference)
    return SecretStr(value)


class EnvSecretStore:
    """Read the secret <name> from the variable KAMAYOQ_SECRET_<NAME>."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        """Keep the mapping to read. The default is the live os.environ."""
        self._environ = os.environ if environ is None else environ

    async def get(self, name: str) -> SecretStr:
        """Return the value of the variable, and make it a known value."""
        check_name(name)
        reference = SECRET_SCHEME + name
        variable = ENV_SECRET_PREFIX + name.upper()
        value = self._environ.get(variable)
        if value is None:
            raise SecretNotFoundError(f"{reference} is not set. Set {variable}")
        return _known_secret(value, reference)


def _read_secret_file(path: Path, reference: str) -> bytes:
    """Return the bytes of a regular file of at most MAX_SECRET_FILE_BYTES.

    Raises:
        SecretNotFoundError: If the file is not a regular file or is too large.
        OSError: If the file cannot be read.
    """
    too_large_message = (
        f"{reference}: {path} is larger than {MAX_SECRET_FILE_BYTES} bytes"
    )
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise SecretNotFoundError(f"{reference}: {path} is not a regular file")
        if status.st_size > MAX_SECRET_FILE_BYTES:
            raise SecretNotFoundError(too_large_message)
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            data = file.read(MAX_SECRET_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(data) > MAX_SECRET_FILE_BYTES:
        raise SecretNotFoundError(too_large_message)
    return data


class FileSecretStore:
    """Read the secret <name> from the file <directory>/<name>, as Docker mounts it."""

    def __init__(self, directory: Path) -> None:
        """Keep the secrets directory."""
        self.directory = directory

    async def get(self, name: str) -> SecretStr:
        """Return the file content with one line end removed, as a known value.

        The file must be a regular file of at most 64 KiB in UTF-8, inside the
        directory.
        """
        check_name(name)
        reference = SECRET_SCHEME + name
        directory = self.directory.resolve()
        path = (directory / name).resolve()
        if not path.is_relative_to(directory):
            raise SecretNotFoundError(f"{reference}: {path} is outside {directory}")
        if not path.exists():
            raise SecretNotFoundError(f"{reference} is not set. Add the file {path}")
        try:
            text = _read_secret_file(path, reference).decode("utf-8")
        except UnicodeDecodeError:
            raise SecretNotFoundError(
                f"{reference}: {path} is not UTF-8 text"
            ) from None
        except OSError as error:
            raise SecretNotFoundError(
                f"{reference}: cannot read {path}: {error.strerror}"
            ) from None
        line_end = "\r\n" if text.endswith("\r\n") else "\n"
        return _known_secret(text.removesuffix(line_end), reference)


def build_secret_store(settings: Settings) -> SecretStore:
    """Return the secret store that KAMAYOQ_SECRETS_BACKEND selects.

    The env backend makes each non-empty KAMAYOQ_SECRET_ value a known value at
    start. The file backend reads no file at start.
    """
    if settings.secrets_backend == "file":
        return FileSecretStore(settings.secrets_dir)
    for variable, value in os.environ.items():
        if variable.startswith(ENV_SECRET_PREFIX) and value:
            remember(value, variable)
    return EnvSecretStore()
