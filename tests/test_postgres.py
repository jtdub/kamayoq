"""Integration tests of the Postgres fixture."""

from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.config import testcontainers_config
from testcontainers.core.docker_client import DockerClient
from testcontainers.core.labels import SESSION_ID


def run_sql(container: PostgresContainer, sql: str) -> str:
    """Run one SQL statement with psql in the container and return the output."""
    result = container.exec(
        [
            "psql",
            "--username",
            container.username,
            "--dbname",
            container.dbname,
            "--tuples-only",
            "--no-align",
            "--command",
            sql,
        ]
    )
    assert result.exit_code == 0, result.output.decode()
    return result.output.decode().strip()


def test_postgres_major_version_is_18(postgres: PostgresContainer) -> None:
    """Run the server of the pinned image."""
    assert run_sql(postgres, "SHOW server_version_num").startswith("18")


def test_pgvector_extension_computes_vector_distance(
    postgres: PostgresContainer,
) -> None:
    """Create the vector extension and compute an L2 distance."""
    run_sql(postgres, "CREATE EXTENSION IF NOT EXISTS vector")
    assert run_sql(postgres, "SELECT '[3,4]'::vector <-> '[0,0]'::vector") == "5"


def test_data_directory_is_on_tmpfs(postgres: PostgresContainer) -> None:
    """Keep the database files in memory, not on the Docker disk."""
    mounts = postgres.exec(["cat", "/proc/mounts"]).output.decode().splitlines()
    assert any(
        line.startswith("tmpfs /var/lib/postgresql ") and "size=1048576k" in line
        for line in mounts
    )


def test_ryuk_runs_the_pinned_image(postgres: PostgresContainer) -> None:
    """Start the cleanup container from the image that conftest pins by digest."""
    client = DockerClient().client
    try:
        ryuk = client.containers.get(f"testcontainers-ryuk-{SESSION_ID}")
        image = ryuk.attrs["Config"]["Image"]
    finally:
        client.close()
    assert "@sha256:" in testcontainers_config.ryuk_image
    assert image == testcontainers_config.ryuk_image
