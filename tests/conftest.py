"""Shared fixtures and markers of the test suite.

A test that uses the postgres fixture is an integration test. Each other test is a
unit test.
"""

import os
import secrets
from collections.abc import Iterator

import pytest
from docker.errors import DockerException
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.config import testcontainers_config
from testcontainers.core.docker_client import DockerClient

PGVECTOR_IMAGE = (
    "pgvector/pgvector:0.8.7-pg18-trixie"
    "@sha256:ab49524d18df7200b74ac9a475e1db6297fc1eb57da4c214c63d10ecc4b754fa"
)
RYUK_IMAGE = (
    "testcontainers/ryuk:0.8.1"
    "@sha256:bf3f74a47dee0acda89aba4b2fc9c7fdcf994a084db02a2d06566f07baae022e"
)
POSTGRES_DATA_DIR = "/var/lib/postgresql"
POSTGRES_TMPFS_OPTIONS = "size=1g"
REQUIRE_DOCKER_ENV = "KAMAYOQ_REQUIRE_DOCKER"
"""Variable that makes a missing Docker an error. Empty and 0 turn it off."""
SETTINGS_ENV_PREFIX = "KAMAYOQ_"


def pytest_configure(config: pytest.Config) -> None:
    """Pin the image of the testcontainers cleanup container."""
    testcontainers_config.ryuk_image = RYUK_IMAGE


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark each test as integration or unit.

    Raises:
        pytest.UsageError: If a test that uses postgres has a unit marker.
    """
    for item in items:
        if "postgres" in getattr(item, "fixturenames", ()):
            if item.get_closest_marker("unit") is not None:
                raise pytest.UsageError(
                    f"{item.nodeid} uses postgres, so it cannot be a unit test."
                )
            item.add_marker(pytest.mark.integration)
        if item.get_closest_marker("integration") is None:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the kamayoq settings of the developer from the environment."""
    for name in list(os.environ):
        if name.startswith(SETTINGS_ENV_PREFIX) and name != REQUIRE_DOCKER_ENV:
            monkeypatch.delenv(name)


def docker_unavailable_reason() -> str | None:
    """Return why Docker cannot run a container, or None if it can."""
    try:
        DockerClient().client.close()
    except DockerException as error:
        return f"Docker is not available: {error}. Start Docker to run this test."
    return None


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    """Start one Postgres 18 container with pgvector for the test session.

    The credentials do not come from the environment, and the password is new for
    each session. The tests skip when Docker is not available, unless
    KAMAYOQ_REQUIRE_DOCKER has a value other than empty or 0. Then they fail.
    """
    reason = docker_unavailable_reason()
    if reason is not None:
        if os.environ.get(REQUIRE_DOCKER_ENV, "") not in ("", "0"):
            pytest.fail(reason)
        pytest.skip(reason)
    container = PostgresContainer(
        PGVECTOR_IMAGE,
        username="kamayoq",
        password=secrets.token_urlsafe(16),
        dbname="kamayoq",
        driver=None,
    ).with_tmpfs_mount(POSTGRES_DATA_DIR, POSTGRES_TMPFS_OPTIONS)
    with container:
        yield container
