"""Create the organizations table and the default org.

Revision ID: 0001
Revises:
Create Date: 2026-11-15 18:19:56.170978
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MINIMUM_SERVER_VERSION = 180000
"""Value of server_version_num for Postgres 18.0, the first with uuidv7()."""


def require_postgres_18() -> None:
    """Stop the migration on a server older than Postgres 18.

    Raises:
        RuntimeError: If the server is older than Postgres 18.
    """
    version = int(op.get_bind().exec_driver_sql("SHOW server_version_num").scalar_one())
    if version < MINIMUM_SERVER_VERSION:
        raise RuntimeError(
            f"kamayoq needs Postgres 18 or later. This server is {version}."
        )


def upgrade() -> None:
    """Upgrade the schema."""
    require_postgres_18()
    organizations = op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("name", name=op.f("uq_organizations_name")),
    )
    op.bulk_insert(
        organizations,
        [{"id": uuid.UUID("01a1e1c3-2028-749d-a7e3-b4f03cd6902e"), "name": "default"}],
    )


def downgrade() -> None:
    """Downgrade the schema."""
    op.drop_table("organizations")
