"""Fill monitors.aqs_code for existing AirNow monitors from dataset_build/airnow_sites.csv.

    alembic upgrade head            # adds monitors.aqs_code (0003)
    python scripts/backfill_monitor_aqs_code.py

Run from backend/ with POSTGRES_HOST/POSTGRES_PORT pointing at the DB. Only rows whose
aqs_code is still null are touched, so it is safe to rerun. New AirNow monitors get the
code from the connector on insert; this is for rows ingested before migration 0003.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.core.config import settings  # noqa: E402
from dataset_build.site_registry import load_registry  # noqa: E402


def main() -> int:
    registry = load_registry()
    filled = 0
    with create_engine(settings.database_url).begin() as c:
        for external_id, site in registry.items():
            filled += c.execute(text("""
                update monitors set aqs_code = :code
                where source = 'airnow' and external_id = :eid and aqs_code is null"""),
                {"code": site["aqs_code"].replace("-", ""), "eid": external_id}).rowcount
        remaining = c.execute(text(
            "select count(*) from monitors where source = 'airnow' and aqs_code is null")).scalar()
    print(f"filled aqs_code on {filled} AirNow monitors; {remaining} AirNow monitors still without one")
    return 1 if remaining else 0


if __name__ == "__main__":
    sys.exit(main())
