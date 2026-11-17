"""Unit tests for the secret stores, the known secret values, and redact."""

import asyncio
import logging
import os
import threading
from pathlib import Path

import pytest
from pydantic import SecretStr

from kamayoq.api.app import create_app
from kamayoq.plugins import protocol_mismatches
from kamayoq.secrets import (
    MASK,
    MAX_SECRET_FILE_BYTES,
    EnvSecretStore,
    FileSecretStore,
    SecretNotFoundError,
    SecretStore,
    build_secret_store,
    forget_all,
    parse_reference,
    redact,
    remember,
    resolve,
)
from kamayoq.settings import Settings

FIXTURE_PROBE_VALUE = "value-of-the-earlier-test"


def test_redact_replaces_each_known_value_and_keeps_other_text() -> None:
    """Replace each known value with the mask, and keep the other text."""
    remember("token-1234", "secret://first")
    remember("hunter22", "secret://second")
    text = "a=token-1234 b=hunter22 c=token-1234 d=plain"
    assert redact(text) == f"a={MASK} b={MASK} c={MASK} d=plain"


def test_redact_with_no_known_value_returns_the_text() -> None:
    """Return the text unchanged when no value is known."""
    assert redact("nothing to hide") == "nothing to hide"


def test_redact_masks_a_value_that_contains_another_value_as_one_span() -> None:
    """Mask the longer value whole when a shorter value is part of it."""
    remember("abcd", "secret://short")
    remember("abcdef", "secret://long")
    assert redact("xabcdefx") == f"x{MASK}x"


def test_redact_masks_a_value_inside_another_value_as_one_span() -> None:
    """Mask the outer value whole when an inner value starts and ends inside it."""
    remember("abcdef", "secret://outer")
    remember("bcde", "secret://inner")
    assert redact("xabcdefx") == f"x{MASK}x"


def test_redact_merges_overlapping_values_into_one_mask() -> None:
    """Leave no part of two values that overlap in the text."""
    remember("abcd", "secret://left")
    remember("cdef", "secret://right")
    assert redact("abcdef") == MASK


def test_redact_merges_values_that_touch() -> None:
    """Replace two values that touch with one mask."""
    remember("abcd", "secret://left")
    remember("efgh", "secret://right")
    assert redact("-abcdefgh-") == f"-{MASK}-"


def test_redact_masks_overlapping_matches_of_one_value() -> None:
    """Mask each start of a value, also when two matches overlap."""
    remember("aaaa", "secret://repeat")
    assert redact("aaaaaa") == MASK


@pytest.mark.parametrize("value", ["abc", "    ", " \t\n "])
def test_remember_does_not_hide_a_short_or_blank_value_and_warns(
    value: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Keep a short or blank value out of the known values, and warn once."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    remember(value, "secret://tiny")
    assert redact(f"x{value}x") == f"x{value}x"
    warnings = [r for r in caplog.records if r.name == "kamayoq.secrets"]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    message = warnings[0].getMessage()
    assert message == (
        "secret://tiny is shorter than 4 characters or is only white space, "
        "so log lines do not hide it"
    )


def test_remember_warns_once_for_each_source_until_forget_all(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warn once for each source, and warn again after forget_all."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    remember("abc", "secret://tiny")
    remember("abc", "secret://tiny")
    remember("abc", "secret://other")
    forget_all()
    remember("abc", "secret://tiny")
    assert [r.getMessage().split(" ")[0] for r in caplog.records] == [
        "secret://tiny",
        "secret://other",
        "secret://tiny",
    ]


def test_remember_hides_a_value_of_four_characters(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Make a value of 4 characters a known value, with no warning."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    remember("abcd", "secret://four")
    assert redact("abcd") == MASK
    assert caplog.records == []


def test_fixture_probe_remembers_a_value() -> None:
    """Remember a value that the next test must not see."""
    remember(FIXTURE_PROBE_VALUE, "secret://probe")
    assert redact(FIXTURE_PROBE_VALUE) == MASK


def test_fixture_forgets_the_value_of_the_earlier_test() -> None:
    """Start each test with no known values."""
    assert redact(FIXTURE_PROBE_VALUE) == FIXTURE_PROBE_VALUE


def test_create_app_hides_the_encoded_and_decoded_database_password() -> None:
    """Make both forms of the database password known values."""
    create_app(Settings(database_url="postgresql://k:p%40ss%2Fw@h:5/d"))
    assert redact("encoded p%40ss%2Fw") == f"encoded {MASK}"
    assert redact("decoded p@ss/w") == f"decoded {MASK}"


def test_create_app_with_no_database_password_adds_no_known_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Add nothing and warn about nothing when the URL has no password."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    url = "postgresql://k@h:5/d"
    create_app(Settings(database_url=url))
    assert redact(url) == url
    assert caplog.records == []


def test_create_app_warns_once_for_a_short_database_password(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Write one warning that names the database password and shows no value."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    create_app(Settings(database_url="postgresql://k:pw@h:5/d"))
    assert [r.getMessage() for r in caplog.records] == [
        "the database password is shorter than 4 characters or is only white space, "
        "so log lines do not hide it"
    ]


NOT_VALID_NAME = (
    "the secret name is not valid. A name has lower-case letters, digits, and _, "
    "starts with a letter, and has at most 128 characters"
)
BAD_SCHEME = "a secret reference must start with secret://"


def get_value(store: SecretStore, name: str) -> str:
    """Return the plain value that the store gives for the name."""
    return asyncio.run(store.get(name)).get_secret_value()


def get_error(store: SecretStore, name: str) -> str:
    """Return the message of the SecretNotFoundError that the store raises."""
    with pytest.raises(SecretNotFoundError) as error_info:
        asyncio.run(store.get(name))
    return str(error_info.value)


def test_parse_reference_returns_the_name() -> None:
    """Return the name part of a valid reference."""
    assert parse_reference("secret://slack_token") == "slack_token"
    assert parse_reference("secret://a" + "b" * 127) == "a" + "b" * 127


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("slack_token", BAD_SCHEME),
        ("Secret://slack_token", BAD_SCHEME),
        ("secret://", NOT_VALID_NAME),
        ("secret://Slack", NOT_VALID_NAME),
        ("secret://a-b", NOT_VALID_NAME),
        ("secret://../x", NOT_VALID_NAME),
        ("secret://1abc", NOT_VALID_NAME),
        ("secret://a" + "b" * 128, NOT_VALID_NAME),
    ],
)
def test_parse_reference_rejects_a_bad_reference_with_no_echo(
    reference: str, message: str
) -> None:
    """Raise the exact message, and do not show the input text."""
    with pytest.raises(SecretNotFoundError) as error_info:
        parse_reference(reference)
    assert str(error_info.value) == message
    assert reference not in str(error_info.value)


def test_env_store_resolves_a_reference_to_a_secret_str() -> None:
    """Give the value of KAMAYOQ_SECRET_<NAME> as a SecretStr that hides it."""
    store = EnvSecretStore({"KAMAYOQ_SECRET_SLACK_TOKEN": "v-123456"})
    value = asyncio.run(resolve(store, "secret://slack_token"))
    assert isinstance(value, SecretStr)
    assert value.get_secret_value() == "v-123456"
    assert "v-123456" not in repr(value)
    assert "v-123456" not in str(value)


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({}, "secret://slack_token is not set. Set KAMAYOQ_SECRET_SLACK_TOKEN"),
        ({"KAMAYOQ_SECRET_SLACK_TOKEN": ""}, "secret://slack_token is empty"),
    ],
)
def test_env_store_rejects_a_missing_or_empty_variable(
    environ: dict[str, str], message: str
) -> None:
    """Raise the exact message for a missing or empty variable."""
    assert get_error(EnvSecretStore(environ), "slack_token") == message


def test_env_store_rejects_a_name_that_is_not_valid() -> None:
    """Check the name before the store reads the environment."""
    store = EnvSecretStore({"KAMAYOQ_SECRET_A-B": "v-123456"})
    assert get_error(store, "a-b") == NOT_VALID_NAME


def test_env_store_reads_the_environment_again_at_each_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """See a rotated value with no restart."""
    store = EnvSecretStore()
    monkeypatch.setenv("KAMAYOQ_SECRET_SLACK_TOKEN", "first-value")
    assert get_value(store, "slack_token") == "first-value"
    monkeypatch.setenv("KAMAYOQ_SECRET_SLACK_TOKEN", "second-value")
    assert get_value(store, "slack_token") == "second-value"


@pytest.mark.parametrize(
    ("content", "value"),
    [
        (b"v-123456", "v-123456"),
        (b"v-123456\n", "v-123456"),
        (b"v-123456\r\n", "v-123456"),
        (b"v-123456\n\n", "v-123456\n"),
        (b"  v 123456\t\n", "  v 123456\t"),
        ("p\u00e4ss-w\u00f6rd\n".encode(), "p\u00e4ss-w\u00f6rd"),
    ],
)
def test_file_store_gives_the_content_with_one_line_end_removed(
    tmp_path: Path, content: bytes, value: str
) -> None:
    """Remove one line end, and keep all other content."""
    (tmp_path / "slack_token").write_bytes(content)
    assert get_value(FileSecretStore(tmp_path), "slack_token") == value


def test_file_store_reads_the_file_again_at_each_get(tmp_path: Path) -> None:
    """See a rotated file with no restart."""
    path = tmp_path / "slack_token"
    store = FileSecretStore(tmp_path)
    path.write_text("first-value", encoding="utf-8")
    assert get_value(store, "slack_token") == "first-value"
    path.write_text("second-value", encoding="utf-8")
    assert get_value(store, "slack_token") == "second-value"


FILE_CONTENT = "file-content-1234"


def file_error(directory: Path) -> str:
    """Return the message of the error that the file store raises for slack_token."""
    return get_error(FileSecretStore(directory), "slack_token")


def test_file_store_rejects_a_missing_file(tmp_path: Path) -> None:
    """Name the file to add."""
    path = tmp_path.resolve() / "slack_token"
    assert file_error(tmp_path) == (
        f"secret://slack_token is not set. Add the file {path}"
    )


@pytest.mark.parametrize("content", [b"", b"\n", b"\r\n"])
def test_file_store_rejects_an_empty_file(tmp_path: Path, content: bytes) -> None:
    """Treat an empty file, or a file with one line end only, as empty."""
    (tmp_path / "slack_token").write_bytes(content)
    assert file_error(tmp_path) == "secret://slack_token is empty"


def test_file_store_rejects_a_directory(tmp_path: Path) -> None:
    """Read regular files only."""
    path = tmp_path.resolve() / "slack_token"
    path.mkdir()
    assert file_error(tmp_path) == f"secret://slack_token: {path} is not a regular file"


def test_file_store_rejects_a_fifo_and_does_not_block(tmp_path: Path) -> None:
    """Return at once for a FIFO that has no writer."""
    path = tmp_path.resolve() / "slack_token"
    os.mkfifo(path)
    messages: list[str] = []
    reader = threading.Thread(
        target=lambda: messages.append(file_error(tmp_path)),
        daemon=True,
    )
    reader.start()
    reader.join(timeout=1)
    assert not reader.is_alive(), "the read of the FIFO blocked"
    assert messages == [f"secret://slack_token: {path} is not a regular file"]


def test_file_store_accepts_a_file_of_64_kib(tmp_path: Path) -> None:
    """Accept a file of exactly the size limit."""
    (tmp_path / "slack_token").write_bytes(b"x" * MAX_SECRET_FILE_BYTES)
    value = get_value(FileSecretStore(tmp_path), "slack_token")
    assert len(value) == MAX_SECRET_FILE_BYTES


def test_file_store_rejects_a_file_of_one_byte_over_64_kib(tmp_path: Path) -> None:
    """Reject a file of the size limit plus one byte, and show no content."""
    path = tmp_path.resolve() / "slack_token"
    content = FILE_CONTENT * (MAX_SECRET_FILE_BYTES // len(FILE_CONTENT) + 1)
    path.write_text(content[: MAX_SECRET_FILE_BYTES + 1], encoding="utf-8")
    message = file_error(tmp_path)
    assert message == f"secret://slack_token: {path} is larger than 65536 bytes"
    assert FILE_CONTENT not in message


def test_file_store_rejects_a_file_that_is_not_utf_8(tmp_path: Path) -> None:
    """Reject bytes that are not UTF-8, with no content and no chained error."""
    path = tmp_path.resolve() / "slack_token"
    path.write_bytes(FILE_CONTENT.encode() + b"\xff\xfe")
    with pytest.raises(SecretNotFoundError) as error_info:
        asyncio.run(FileSecretStore(tmp_path).get("slack_token"))
    message = str(error_info.value)
    assert message == f"secret://slack_token: {path} is not UTF-8 text"
    assert FILE_CONTENT not in message
    assert error_info.value.__cause__ is None
    assert error_info.value.__suppress_context__ is True


def test_file_store_rejects_a_link_to_a_file_outside_the_directory(
    tmp_path: Path,
) -> None:
    """Do not follow a symbolic link out of the secrets directory."""
    directory = tmp_path.resolve() / "secrets"
    directory.mkdir()
    outside = tmp_path.resolve() / "outside"
    outside.write_text(FILE_CONTENT, encoding="utf-8")
    (directory / "slack_token").symlink_to(outside)
    message = file_error(directory)
    assert message == f"secret://slack_token: {outside} is outside {directory}"
    assert FILE_CONTENT not in message


def test_file_store_follows_a_link_inside_the_directory(tmp_path: Path) -> None:
    """Read a link to a file in the same directory, as Kubernetes mounts do."""
    (tmp_path / "real").write_text("v-123456", encoding="utf-8")
    (tmp_path / "slack_token").symlink_to(tmp_path / "real")
    assert get_value(FileSecretStore(tmp_path), "slack_token") == "v-123456"


def test_file_store_reports_an_os_error_with_no_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Give the error text of the system, and no content."""
    path = tmp_path.resolve() / "slack_token"
    path.write_text(FILE_CONTENT, encoding="utf-8")

    def refuse(*args: object, **kwargs: object) -> int:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("kamayoq.secrets.os.open", refuse)
    with pytest.raises(SecretNotFoundError) as error_info:
        asyncio.run(FileSecretStore(tmp_path).get("slack_token"))
    assert str(error_info.value) == (
        f"secret://slack_token: cannot read {path}: Permission denied"
    )
    assert error_info.value.__suppress_context__ is True


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_file_store_reports_a_directory_with_no_search_permission(
    tmp_path: Path,
) -> None:
    """Give the cannot read message when the store cannot look in the directory."""
    directory = tmp_path.resolve() / "locked"
    directory.mkdir()
    directory.chmod(0o600)
    try:
        message = file_error(directory)
    finally:
        directory.chmod(0o700)
    assert message == (
        f"secret://slack_token: cannot read {directory / 'slack_token'}: "
        "Permission denied"
    )


def test_file_store_reports_a_link_loop(tmp_path: Path) -> None:
    """Give the cannot read message for a link to itself."""
    path = tmp_path.resolve() / "slack_token"
    path.symlink_to(path)
    assert file_error(tmp_path) == (
        f"secret://slack_token: cannot read {path}: Too many levels of symbolic links"
    )


def test_file_store_rejects_a_name_that_is_not_valid(tmp_path: Path) -> None:
    """Check the name before the store reads a file."""
    (tmp_path / "Slack").write_text("v-123456", encoding="utf-8")
    assert get_error(FileSecretStore(tmp_path), "Slack") == NOT_VALID_NAME


def test_each_store_makes_its_value_a_known_value(tmp_path: Path) -> None:
    """Hide the value that a store returns in later log lines."""
    (tmp_path / "file_token").write_text("from-a-file\n", encoding="utf-8")
    get_value(FileSecretStore(tmp_path), "file_token")
    get_value(EnvSecretStore({"KAMAYOQ_SECRET_ENV_TOKEN": "from-env"}), "env_token")
    assert redact("a=from-a-file b=from-env") == f"a={MASK} b={MASK}"


def test_store_warns_for_a_short_value_and_names_the_reference(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Return a short value at each get, and write one warning with no value."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    store = EnvSecretStore({"KAMAYOQ_SECRET_PIN": "123"})
    assert get_value(store, "pin") == "123"
    assert get_value(store, "pin") == "123"
    assert [r.getMessage() for r in caplog.records] == [
        "secret://pin is shorter than 4 characters or is only white space, "
        "so log lines do not hide it"
    ]


@pytest.mark.parametrize("store_class", [EnvSecretStore, FileSecretStore])
def test_store_matches_the_secret_store_protocol(store_class: type) -> None:
    """Match SecretStore with the plugin check."""
    assert protocol_mismatches(store_class, SecretStore) == []


DATABASE_URL = "postgresql://k@h:5/d"


def test_env_backend_makes_each_secret_variable_a_known_value_at_start(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Hide each KAMAYOQ_SECRET_ value of 4 or more characters before any get."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    monkeypatch.setenv("KAMAYOQ_SECRET_SLACK_TOKEN", "xoxb-1234")
    monkeypatch.setenv("KAMAYOQ_SECRET_MCP_KEY", "mcp-key-5678")
    monkeypatch.setenv("KAMAYOQ_SECRET_EMPTY", "")
    monkeypatch.setenv("KAMAYOQ_SECRET_PIN", "123")
    monkeypatch.setenv("OTHER_TOKEN", "not-a-secret")
    monkeypatch.setenv("KAMAYOQ_NOT_A_SECRET", "kamayoq-setting")
    store = build_secret_store(Settings(database_url=DATABASE_URL))
    assert isinstance(store, EnvSecretStore)
    assert redact("xoxb-1234 mcp-key-5678 not-a-secret kamayoq-setting 123") == (
        f"{MASK} {MASK} not-a-secret kamayoq-setting 123"
    )
    assert [r.getMessage() for r in caplog.records] == [
        "KAMAYOQ_SECRET_PIN is shorter than 4 characters or is only white space, "
        "so log lines do not hide it"
    ]


def test_file_backend_reads_no_file_at_start(tmp_path: Path) -> None:
    """Give a FileSecretStore for the directory, and add no known value."""
    (tmp_path / "slack_token").write_text("v-123456", encoding="utf-8")
    settings = Settings(
        database_url=DATABASE_URL, secrets_backend="file", secrets_dir=tmp_path
    )
    store = build_secret_store(settings)
    assert isinstance(store, FileSecretStore)
    assert store.directory == tmp_path
    assert redact("v-123456") == "v-123456"


def test_create_app_holds_an_env_store_by_default() -> None:
    """Put an EnvSecretStore in app.state.secrets."""
    app = create_app(Settings(database_url=DATABASE_URL))
    assert isinstance(app.state.secrets, EnvSecretStore)


def test_create_app_holds_a_file_store_for_the_file_backend(tmp_path: Path) -> None:
    """Put a FileSecretStore of the secrets directory in app.state.secrets."""
    settings = Settings(
        database_url=DATABASE_URL, secrets_backend="file", secrets_dir=tmp_path
    )
    app = create_app(settings)
    assert isinstance(app.state.secrets, FileSecretStore)
    assert app.state.secrets.directory == tmp_path


def test_env_backend_warns_once_at_start_and_once_for_the_reference(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Name the variable at start and the reference at the first get only."""
    caplog.set_level(logging.WARNING, logger="kamayoq.secrets")
    monkeypatch.setenv("KAMAYOQ_SECRET_PIN", "123")
    store = build_secret_store(Settings(database_url=DATABASE_URL))
    get_value(store, "pin")
    get_value(store, "pin")
    assert [r.getMessage().split(" ")[0] for r in caplog.records] == [
        "KAMAYOQ_SECRET_PIN",
        "secret://pin",
    ]
