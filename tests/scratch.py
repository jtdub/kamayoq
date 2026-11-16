"""Declarative base of the test models."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from kamayoq.db.base import NAMING_CONVENTION


class ScratchBase(DeclarativeBase):
    """Hold the test models, so that Base.metadata holds only the real tables."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
