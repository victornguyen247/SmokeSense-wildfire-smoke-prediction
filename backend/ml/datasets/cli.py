"""Command-line entry point for DATA-04.

Run from backend/: python -m ml.datasets.cli --help
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ml.datasets.build import build_versioned_dataset
from ml.datasets.loader import load_event_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the SmokeSense DATA-04 Parquet artifact")
    parser.add_argument("--version", required=True, help="Version ID, e.g. v1-draft")
    parser.add_argument("--output-root", required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--table", help="PostgreSQL table, e.g. schema.table")
    source.add_argument("--sql-file", type=Path, help="Reviewed read-only SQL containing :event_ids")
    source.add_argument("--from-parquet", type=Path, help="Local GEO-01 Parquet (testing only)")
    parser.add_argument("--event-id", action="append", default=[], help="Repeat for each pilot event")
    parser.add_argument("--event-column", default="pilot_event_id")
    parser.add_argument("--db-env", default="DATABASE_URL", help="Name of DB URL env var (never its value)")
    args = parser.parse_args()
    if args.from_parquet:
        df = pd.read_parquet(args.from_parquet)
        if args.event_id:
            df = df.loc[df["pilot_event_id"].isin(args.event_id)].copy()
    else:
        if not args.event_id:
            parser.error("--event-id required for database loading")
        df = load_event_rows(args.event_id, table=args.table, sql_file=args.sql_file,
                             event_column=args.event_column, database_url_env=args.db_env)
    destination = build_versioned_dataset(df, version=args.version, output_root=args.output_root)
    print(f"Dataset generated at: {destination}")
    print("Before sharing: PM-01/ML owner must approve column contract, source provenance, and event holdouts.")


if __name__ == "__main__":
    main()
