"""AirNow site registry: monitor external_id -> AQS code, name, coordinates.

The DB stores AirNow monitors under a hash of their AQS code
(stable_external_id("airnow", code)), so the code itself is not queryable.
The dataset build needs it for the California scope (app/core/scope.py), so
this registry is generated once and committed as airnow_sites.csv.

    python -m dataset_build.site_registry [--cache DIR]

It hashes every AQS code seen in raw AirNow responses (default: the cache of
scripts/pilot_verification, PILOT_VERIFY_CACHE) and keeps the codes that match
an AirNow monitor in the DB. Point the DB at it with POSTGRES_HOST/POSTGRES_PORT.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[1]
REGISTRY = Path(__file__).resolve().parent / "airnow_sites.csv"
FIELDS = ("external_id", "aqs_code", "name", "latitude", "longitude", "state_code")


def load_registry(path: Path = REGISTRY) -> dict[str, dict]:
    """{external_id: {aqs_code, name, latitude, longitude, state_code}}."""
    with path.open(newline="") as f:
        return {r["external_id"]: r for r in csv.DictReader(f)}


def main() -> int:
    sys.path.insert(0, str(BACKEND))
    from app.core.config import settings
    from ingestion.connectors.airnow import normalize_aqs_code
    from ingestion.normalize import stable_external_id

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    default_cache = os.environ.get("PILOT_VERIFY_CACHE") or BACKEND / "scripts/pilot_verification/.cache"
    ap.add_argument("--cache", default=str(default_cache), help="dir holding airnow_cache/*.json")
    args = ap.parse_args()

    codes = {}
    for f in (Path(args.cache) / "airnow_cache").glob("*.json"):
        for r in json.loads(f.read_text()):
            if r.get("FullAQSCode"):
                code = normalize_aqs_code(str(r["FullAQSCode"]))
                codes.setdefault(stable_external_id("airnow", code), (code, r))

    with create_engine(settings.database_url).connect() as c:
        monitors = c.execute(text("""
            select external_id, name, ST_Y(geom::geometry) lat, ST_X(geom::geometry) lon
            from monitors where source = 'airnow' order by name""")).mappings().all()

    rows, missing = [], []
    for m in monitors:
        hit = codes.get(m["external_id"])
        if not hit:
            missing.append(m["name"])
            continue
        code, _ = hit
        rows.append({"external_id": m["external_id"], "aqs_code": f"{code[:2]}-{code[2:5]}-{code[5:]}",
                     "name": " ".join(m["name"].split()), "latitude": round(m["lat"], 6),
                     "longitude": round(m["lon"], 6), "state_code": code[:2]})
    with REGISTRY.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["aqs_code"]))
    print(f"{len(rows)} of {len(monitors)} AirNow monitors written to {REGISTRY.name}"
          + (f"; no AQS code found for: {', '.join(missing)}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
