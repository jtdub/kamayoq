"""Models of kamayoq.

Put each new model in this module, or import it here, so that Alembic sees it.
"""

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from kamayoq.db.base import Base, RecordColumns

__all__ = ["DEFAULT_ORG_ID", "DEFAULT_ORG_NAME", "Base", "Organization"]

DEFAULT_ORG_ID = uuid.UUID("01a1e1c3-2028-749d-a7e3-b4f03cd6902e")
"""ID of the org that the first migration inserts. Do not change it."""

DEFAULT_ORG_NAME = "default"


class Organization(RecordColumns, Base):
    """Tenant that owns each org-scoped row.

    The unique constraint on name does not include org_id, because this is the
    tenant table.
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), unique=True)
