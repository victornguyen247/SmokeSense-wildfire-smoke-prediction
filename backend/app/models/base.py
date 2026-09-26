"""Declarative base and shared column helpers.

The models mirror migrations/versions/0001_initial_schema.py exactly — same
types, constraints, and index names — so `alembic revision --autogenerate`
produces an empty diff. Change the schema with a migration first, then here.
"""

from collections.abc import Iterable
from datetime import date, datetime

from geoalchemy2 import Geography
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Double, Integer, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # Python type → DB type, matching the migration's raw SQL:
    # TEXT, TIMESTAMPTZ (UTC everywhere), FLOAT (= double precision), INT, BOOLEAN, DATE.
    type_annotation_map = {
        str: Text(),
        datetime: DateTime(timezone=True),
        float: Double(),
        int: Integer(),
        bool: Boolean(),
        date: Date(),
    }


def point() -> Geography:
    """GEOGRAPHY(POINT, 4326). GiST indexes are declared explicitly per table
    (as in the migration), so GeoAlchemy2's automatic index is turned off."""
    return Geography(geometry_type="POINT", srid=4326, spatial_index=False)


def one_of(column: str, values: Iterable) -> CheckConstraint:
    """TEXT + CHECK value list, e.g. CHECK (kind IN ('city','zip'))."""
    return CheckConstraint(f"{column} IN ({', '.join(repr(v) for v in values)})")
