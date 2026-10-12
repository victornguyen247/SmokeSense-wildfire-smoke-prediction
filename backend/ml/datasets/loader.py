"""Read-only SQL loader; DB credentials are provided via environment variables."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, create_engine, text

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quoted_identifier(name: str) -> str:
    parts = name.split(".")
    if not (1 <= len(parts) <= 2) or any(not _IDENTIFIER.fullmatch(p) for p in parts):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return ".".join('"' + p + '"' for p in parts)


def load_event_rows(
    event_ids: list[str],
    *,
    table: str | None = None,
    event_column: str = "pilot_event_id",
    sql_file: str | Path | None = None,
    database_url_env: str = "DATABASE_URL",
) -> pd.DataFrame:
    """Read GEO-01 materialized rows for an event list; never print credentials.

    Custom SQL must use `:event_ids` in an IN clause, e.g. WHERE x IN :event_ids.
    All custom SQL comes from a reviewed local file, not external user input.
    """
    if not event_ids or any(not isinstance(e, str) or not e.strip() for e in event_ids):
        raise ValueError("Provide at least one nonempty event ID")
    if len(event_ids) > 1000:
        raise ValueError("At most 1000 event IDs per call")
    if (table is None) == (sql_file is None):
        raise ValueError("Specify exactly one of table or sql_file")
    if table is not None:
        sql = (f"SELECT * FROM {_quoted_identifier(table)} "
               f"WHERE {_quoted_identifier(event_column)} IN :event_ids")
    else:
        sql = Path(sql_file).read_text(encoding="utf-8").strip().rstrip(";")
        if not sql.lower().lstrip().startswith(("select ", "with ")):
            raise ValueError("Custom SQL must be a read-only SELECT/WITH query")
        if ":event_ids" not in sql:
            raise ValueError("Custom SQL must contain the :event_ids expanding bind parameter")
    database_url = os.environ.get(database_url_env)
    if not database_url:
        raise RuntimeError(f"Missing database URL environment variable: {database_url_env}")
    statement = text(sql).bindparams(bindparam("event_ids", expanding=True))
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            return pd.read_sql_query(statement, conn, params={"event_ids": list(dict.fromkeys(event_ids))})
    finally:
        engine.dispose()
