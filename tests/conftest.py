"""Shared fixtures and markers of the test suite.

A test that uses the postgres or keycloak fixture is an integration test. Each other
test is a unit test.
"""

import ipaddress
import os
import secrets
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from docker.errors import DockerException
from psycopg import sql
from scratch import ScratchBase
from sqlalchemy import MetaData
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.config import testcontainers_config
from testcontainers.core.container import DockerContainer
from testcontainers.core.docker_client import DockerClient
from testcontainers.core.wait_strategies import HttpWaitStrategy

from kamayoq.db.models import Base
from kamayoq.secrets import forget_all
from kamayoq.settings import ENV_PREFIX

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
KEYCLOAK_IMAGE = (
    "quay.io/keycloak/keycloak:26.8.2-1"
    "@sha256:723b1d6e254c0fc96d5cffec860c7e0744d6a3277822b865bb538cf891575e41"
)
KEYCLOAK_PORT = 8080
KEYCLOAK_REALM_DIR = Path(__file__).resolve().parent / "keycloak"
KEYCLOAK_IMPORT_DIR = "/opt/keycloak/data/import"
KEYCLOAK_READY_PATH = "/realms/kamayoq-test/.well-known/openid-configuration"
REQUIRE_DOCKER_ENV = "KAMAYOQ_REQUIRE_DOCKER"
"""Variable that makes a missing Docker an error. Empty and 0 turn it off."""
INTEGRATION_FIXTURES = ("postgres", "keycloak")
"""Fixtures that start a container. Each test that uses one is an integration test."""


def pytest_configure(config: pytest.Config) -> None:
    """Pin the image of the testcontainers cleanup container."""
    testcontainers_config.ryuk_image = RYUK_IMAGE


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark each test as integration or unit.

    Raises:
        pytest.UsageError: If a test that uses a container fixture has a unit marker.
    """
    for item in items:
        fixturenames = getattr(item, "fixturenames", ())
        for fixture in INTEGRATION_FIXTURES:
            if fixture not in fixturenames:
                continue
            if item.get_closest_marker("unit") is not None:
                raise pytest.UsageError(
                    f"{item.nodeid} uses {fixture}, so it cannot be a unit test."
                )
            item.add_marker(pytest.mark.integration)
        if item.get_closest_marker("integration") is None:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the kamayoq settings of the developer from the environment."""
    for name in list(os.environ):
        if name.startswith(ENV_PREFIX) and name != REQUIRE_DOCKER_ENV:
            monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def forget_secret_values() -> Iterator[None]:
    """Start and end each test with no known secret values."""
    forget_all()
    yield
    forget_all()


def docker_unavailable_reason() -> str | None:
    """Return why Docker cannot run a container, or None if it can."""
    try:
        DockerClient().client.close()
    except DockerException as error:
        return f"Docker is not available: {error}. Start Docker to run this test."
    return None


def require_docker() -> None:
    """Skip the test when Docker is not available.

    The test fails in place of a skip when KAMAYOQ_REQUIRE_DOCKER has a value other
    than empty or 0.
    """
    reason = docker_unavailable_reason()
    if reason is not None:
        if os.environ.get(REQUIRE_DOCKER_ENV, "") not in ("", "0"):
            pytest.fail(reason)
        pytest.skip(reason)


def is_loopback_host(host: str) -> bool:
    """Return True if the host is localhost or a loopback IP address."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    """Start one Postgres 18 container with pgvector for the test session.

    The credentials do not come from the environment, and the password is new for
    each session. The skip and fail rule of require_docker applies.
    """
    require_docker()
    container = PostgresContainer(
        PGVECTOR_IMAGE,
        username="kamayoq",
        password=secrets.token_urlsafe(16),
        dbname="kamayoq",
        driver=None,
    ).with_tmpfs_mount(POSTGRES_DATA_DIR, POSTGRES_TMPFS_OPTIONS)
    with container:
        yield container


@pytest.fixture(scope="session")
def keycloak() -> Iterator[str]:
    """Start one Keycloak container with the test realms, and yield its base URL.

    The URL is always http://localhost:<port>, because Keycloak puts the request
    host in the iss claim and the issuer setting permits only a loopback http URL.
    The skip and fail rule of require_docker applies.
    """
    require_docker()
    container = (
        DockerContainer(KEYCLOAK_IMAGE)
        .with_exposed_ports(KEYCLOAK_PORT)
        .with_command("start-dev --import-realm")
        .with_volume_mapping(KEYCLOAK_REALM_DIR, KEYCLOAK_IMPORT_DIR, "ro")
        .with_env("KC_BOOTSTRAP_ADMIN_USERNAME", "admin")
        .with_env("KC_BOOTSTRAP_ADMIN_PASSWORD", secrets.token_urlsafe(16))
        .waiting_for(HttpWaitStrategy(KEYCLOAK_PORT, KEYCLOAK_READY_PATH))
    )
    with container:
        if not is_loopback_host(container.get_container_host_ip()):
            pytest.fail("The Keycloak tests need Docker on this host.")
        yield f"http://localhost:{container.get_exposed_port(KEYCLOAK_PORT)}"


@pytest.fixture
def empty_database_url(postgres: PostgresContainer) -> Iterator[str]:
    """Create a new empty database for one test, and yield its libpq URL."""
    name = "kamayoq_test_" + secrets.token_hex(8)
    server_url = postgres.get_connection_url()
    with psycopg.connect(server_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    yield server_url.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(server_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
        )


@pytest.fixture
def scratch_metadata() -> Iterator[MetaData]:
    """Give the test a ScratchBase with a copy of organizations only."""
    Base.metadata.tables["organizations"].to_metadata(ScratchBase.metadata)
    yield ScratchBase.metadata
    ScratchBase.registry.dispose()
    ScratchBase.metadata.clear()
