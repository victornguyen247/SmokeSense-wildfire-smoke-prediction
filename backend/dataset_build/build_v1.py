"""Build the SmokeSense v1 training dataset (DATA-04) from the local DB.

    python -m dataset_build.build_v1 [--out data/datasets/smokesense_v1] [--only PE-001 ...]

Run from backend/ with POSTGRES_HOST/POSTGRES_PORT pointing at the DB. Rules are
docs/data-decisions.md #17-22:

  points  (18) per event, AirNow monitors with valid regulatory pm25 inside the tight bbox
          during [start, end] and in California scope; forecast_point_id = monitors.external_id
  times   (19) every UTC hour in [start 00:00, end 23:00] x ALLOWED_HORIZONS
  inputs  (20) fires: VIIRS_SNPP in firms_bbox x [firms_start_date, end];
          PM2.5 history and labels: regulatory AirNow in the tight bbox x [airnow_start_date,
          airnow_end_date]; weather: weather_observations in ncei_bbox x [ncei_start_date, end];
          build_feature_dataset(..., lookback_hours=72)
  dedupe  (21) one row per (forecast_point_id, issue_time, horizon_hours); event_ids lists every
          event that produced it, pilot_event_id is the first; group_id groups events whose
          windows overlap (connected components)

Each event's rows are checked for leakage (dataset_build/checks.py) before dedupe. Writes
data.parquet and manifest.json to the output folder (gitignored).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.core.config import settings  # noqa: E402
from app.core.scope import in_california_scope  # noqa: E402
from dataset_build.checks import check_event  # noqa: E402
from dataset_build.site_registry import load_registry  # noqa: E402
from features.alignment import ALLOWED_HORIZONS, build_feature_dataset  # noqa: E402
from features.validation import validate_feature_dataset  # noqa: E402
from ingestion.batch.batch_ingest import PilotEvent, load_pilot_events  # noqa: E402

VERSION = "1.0.0"
CONFIG = BACKEND / "docs" / "pilot_events.json"
OUT = BACKEND / "data" / "datasets" / "smokesense_v1"
SNPP = "VIIRS_SNPP"  # fire_detections.satellite for VIIRS SNPP (ingestion/connectors/firms.py)
LOOKBACK_HOURS = 72.0
KEY = ["forecast_point_id", "issue_time", "horizon_hours"]

# Column dtypes from the Parquet contract (docs/schema.md); precip_1h_mm follows the other weather floats.
FLOAT32 = ["location_lat", "location_lon", "target_pm25", "target_monitor_dist_km", "nearest_fire_dist_km",
           "fire_bearing_deg", "fire_bearing_sin", "fire_bearing_cos", "total_frp_200km", "wind_alignment",
           "wind_speed_ms", "wind_dir_sin", "wind_dir_cos", "temp_c", "rh_pct", "pressure_hpa", "precip_1h_mm",
           "precip_prob_pct", "pm25_lag_1h", "pm25_lag_3h", "pm25_lag_6h", "pm25_lag_12h", "pm25_lag_24h",
           "local_solar_hour"]
DTYPES = {**{c: "float32" for c in FLOAT32}, "horizon_hours": "int8", "active_fire_count_200km": "int16",
          "day_of_year": "int16", "month": "int8", "smoke_season": "bool"}
STRINGS = ["forecast_point_id", "pilot_event_id", "target_source", "target_monitor_id", "event_tier", "group_id"]


def utc_day(d: str) -> datetime:
    return datetime.fromisoformat(d).replace(tzinfo=timezone.utc)


def issue_times(start: str, end: str) -> pd.Series:
    """Every UTC hour from start 00:00 to end 23:00 (entry 19)."""
    return pd.Series(pd.date_range(utc_day(start), utc_day(end) + timedelta(hours=23), freq="h"))


def overlap_groups(events: list[PilotEvent]) -> dict[str, str]:
    """group_id per event: connected components of events whose [start, end] windows overlap."""
    parent = {e.event_id: e.event_id for e in events}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(events):
        for b in events[i + 1:]:
            if a.start_date <= b.end_date and b.start_date <= a.end_date:
                parent[find(a.event_id)] = find(b.event_id)
    members: dict[str, list[str]] = {}
    for e in events:
        members.setdefault(find(e.event_id), []).append(e.event_id)
    return {eid: f"G-{min(m)}" for m in members.values() for eid in m}


def _box(b: str) -> dict:
    w, s, e, n = (float(v) for v in b.split(","))
    return {"w": w, "s": s, "e": e, "n": n}


ENV = "ST_MakeEnvelope(:w, :s, :e, :n, 4326)"


def resolve_aqs(rows: pd.DataFrame, registry: dict, event_id: str = "") -> pd.Series:
    """AQS code per row: monitors.aqs_code (#32), else the airnow_sites.csv registry (with a warning)."""
    codes = rows["aqs_code"].astype("object").where(rows["aqs_code"].notna(), None)
    missing = rows.loc[codes.isna(), "forecast_point_id"]
    if len(missing):
        from_csv = {m: registry[m]["aqs_code"] for m in missing if m in registry}
        unknown = sorted(set(missing) - set(from_csv))
        if unknown:
            raise SystemExit(f"{event_id}: no AQS code in monitors.aqs_code or airnow_sites.csv for {unknown}; "
                             "run scripts/backfill_monitor_aqs_code.py")
        print(f"warning: {event_id}: monitors.aqs_code is null for {len(from_csv)} monitor(s); using "
              "airnow_sites.csv (run scripts/backfill_monitor_aqs_code.py)", file=sys.stderr)
        codes = codes.where(codes.notna(), rows["forecast_point_id"].map(from_csv))
    return codes.map(lambda c: c.replace("-", ""))


def forecast_points(c, ev: PilotEvent, registry: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Entry 18: in-box AirNow monitors with valid pm25 during the event, in California scope."""
    rows = pd.read_sql(text(f"""
        select distinct m.external_id as forecast_point_id, m.name, m.aqs_code,
               ST_Y(m.geom::geometry) as location_lat, ST_X(m.geom::geometry) as location_lon
        from observations o join monitors m on m.id = o.monitor_id
        where m.source = 'airnow' and o.correction = 'regulatory' and o.pm25 is not null
          and o.valid_at >= :lo and o.valid_at < :hi and ST_Intersects(m.geom::geometry, {ENV})"""),
        c, params=dict(lo=utc_day(ev.start_date), hi=utc_day(ev.end_date) + timedelta(days=1), **_box(ev.bbox)))
    rows["aqs_code"] = resolve_aqs(rows, registry, ev.event_id)
    keep = rows["aqs_code"].map(in_california_scope)
    dropped = [{"event": ev.event_id, "name": r.name, "aqs": f"{r.aqs_code[:2]}-{r.aqs_code[2:5]}-{r.aqs_code[5:]}"}
               for r in rows[~keep].itertuples()]
    return rows[keep].drop(columns="name").reset_index(drop=True), dropped


def load_inputs(c, ev: PilotEvent) -> dict[str, pd.DataFrame]:
    """Entry 20: each source's frame over its own bbox and window."""
    end = utc_day(ev.end_date) + timedelta(days=1)
    fires = pd.read_sql(text(f"""
        select detected_at, ST_Y(geom::geometry) as latitude, ST_X(geom::geometry) as longitude, frp_mw
        from fire_detections
        where satellite = :sat and detected_at >= :lo and detected_at < :hi
          and ST_Intersects(geom::geometry, {ENV})"""),
        c, params=dict(sat=SNPP, lo=utc_day(ev.firms_start_date), hi=end, **_box(ev.firms_bbox)))
    obs = pd.read_sql(text(f"""
        select m.external_id as monitor_id, o.valid_at, o.pm25, o.correction, o.qa_flag,
               ST_Y(m.geom::geometry) as latitude, ST_X(m.geom::geometry) as longitude
        from observations o join monitors m on m.id = o.monitor_id
        where m.source = 'airnow' and o.correction = 'regulatory' and o.pm25 is not null
          and o.valid_at >= :lo and o.valid_at < :hi and ST_Intersects(m.geom::geometry, {ENV})"""),
        c, params=dict(lo=utc_day(ev.airnow_start_date), hi=utc_day(ev.airnow_end_date) + timedelta(days=1),
                       **_box(ev.bbox)))
    weather = pd.read_sql(text(f"""
        select station_id, valid_at, ST_Y(geom::geometry) as latitude, ST_X(geom::geometry) as longitude,
               wind_speed_ms, wind_dir_deg, temp_c, rh_pct, pressure_hpa, precip_1h_mm
        from weather_observations
        where valid_at >= :lo and valid_at < :hi and ST_Intersects(geom::geometry, {ENV})"""),
        c, params=dict(lo=utc_day(ev.ncei_start_date), hi=end, **_box(ev.ncei_bbox)))
    for f, col in ((fires, "detected_at"), (obs, "valid_at"), (weather, "valid_at")):
        f[col] = pd.to_datetime(f[col], utc=True)
    history = obs.rename(columns={"monitor_id": "forecast_point_id", "valid_at": "issue_time"})[
        ["forecast_point_id", "issue_time", "pm25"]]
    return {"fires": fires, "pm25_history": history, "pm25_observations": obs, "weather": weather}


def build_event(c, ev: PilotEvent, registry: dict) -> tuple[pd.DataFrame, dict]:
    points, dropped = forecast_points(c, ev, registry)
    frames = load_inputs(c, ev)
    info_codes = dict(zip(points["forecast_point_id"], points["aqs_code"]))
    points = points.drop(columns="aqs_code")
    rows = build_feature_dataset(
        forecast_points=points, issue_times=issue_times(ev.start_date, ev.end_date),
        fire_detections=frames["fires"], pm25_history=frames["pm25_history"],
        weather_observations=frames["weather"], pm25_observations=frames["pm25_observations"],
        pilot_event_id=ev.event_id, horizons=ALLOWED_HORIZONS, lookback_hours=LOOKBACK_HOURS)
    checked = check_event(rows, frames)
    info = {"forecast_points": len(points), "out_of_scope": dropped, "rows": len(rows), "_aqs": info_codes,
            "inputs": {k: len(v) for k, v in frames.items()}, "leakage_rows_checked": checked}
    return rows, info


def dedupe(per_event: dict[str, pd.DataFrame], tiers: dict[str, str], groups: dict[str, str]) -> pd.DataFrame:
    """Entry 21: one row per key; event_ids lists every event, pilot_event_id is the first."""
    allrows = pd.concat([df.assign(_event=eid) for eid, df in sorted(per_event.items())], ignore_index=True)
    ids = allrows.groupby(KEY)["_event"].agg(lambda s: sorted(set(s))).rename("event_ids").reset_index()
    out = allrows.sort_values("_event", kind="mergesort").drop_duplicates(KEY, keep="first")
    out = out.drop(columns=["_event", "pilot_event_id"]).merge(ids, on=KEY, how="left", validate="one_to_one")
    out["pilot_event_id"] = out["event_ids"].map(lambda e: e[0])
    out["event_tier"] = out["pilot_event_id"].map(tiers)
    out["group_id"] = out["pilot_event_id"].map(groups)
    return out.sort_values(["pilot_event_id", "forecast_point_id", "issue_time", "horizon_hours"]).reset_index(drop=True)


def cast(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col, dtype in DTYPES.items():
        if dtype == "bool":
            df[col] = df[col].astype(bool)
        elif dtype.startswith("int"):
            df[col] = pd.to_numeric(df[col]).astype(dtype)
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(dtype)
    for col in ("issue_time", "target_time"):
        df[col] = pd.to_datetime(df[col], utc=True)
    for col in STRINGS:
        if col in df:
            df[col] = df[col].astype("string")
    return df


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stats(df: pd.DataFrame) -> dict:
    label = df["target_pm25"].astype(float)

    def dist(s):
        return {"rows": int(len(s)), "mean": round(float(s.mean()), 2), "p50": round(float(s.quantile(0.5)), 2),
                "p95": round(float(s.quantile(0.95)), 2), "pct_ge_35_5": round(100 * float((s >= 35.5).mean()), 2)}

    feature_cols = [c for c in df.columns if c not in KEY + ["target_time", "event_ids", "pilot_event_id",
                                                             "event_tier", "group_id", "target_pm25",
                                                             "target_source", "target_monitor_id",
                                                             "target_monitor_dist_km", "location_lat",
                                                             "location_lon"]]
    return {
        "rows": int(len(df)),
        "rows_per_event": {k: int(v) for k, v in df["pilot_event_id"].value_counts().sort_index().items()},
        "rows_per_group": {k: int(v) for k, v in df["group_id"].value_counts().sort_index().items()},
        "rows_per_horizon": {str(k): int(v) for k, v in df["horizon_hours"].value_counts().sort_index().items()},
        "rows_shared_by_events": int((df["event_ids"].map(len) > 1).sum()),
        "label": dist(label),
        "label_per_tier": {t: dist(label[df["event_tier"] == t]) for t in sorted(df["event_tier"].dropna().unique())},
        "null_rate_pct": {c: round(100 * float(df[c].isna().mean()), 2) for c in sorted(feature_cols)},
    }


def git_commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND, capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=BACKEND,
                               capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--only", nargs="+", metavar="EVENT_ID")
    args = ap.parse_args()

    t0 = time.time()
    events = load_pilot_events(CONFIG)
    groups = overlap_groups(events)
    tiers = {e.event_id: e.tier for e in events}
    registry = load_registry()
    per_event, info = {}, {}
    with create_engine(settings.database_url).connect() as c:
        for ev in events:
            if args.only and ev.event_id not in args.only:
                continue
            t = time.time()
            per_event[ev.event_id], info[ev.event_id] = build_event(c, ev, registry)
            print(f"{ev.event_id}: {info[ev.event_id]['forecast_points']} points, {info[ev.event_id]['rows']:,} rows, "
                  f"leakage checks {info[ev.event_id]['leakage_rows_checked']} ({time.time() - t:.0f}s)", flush=True)

    df = cast(dedupe(per_event, tiers, groups))
    validate_feature_dataset(df)
    if df.duplicated(KEY).any():
        raise SystemExit("duplicate (forecast_point_id, issue_time, horizon_hours) rows after dedupe")
    aqs = {m: code for i in info.values() for m, code in i.pop("_aqs").items()}
    out_of_scope = [m for m in df["forecast_point_id"].unique() if not in_california_scope(aqs[m])]
    if out_of_scope:
        raise SystemExit(f"forecast points outside California scope: {out_of_scope}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    parquet = out / "data.parquet"
    df.to_parquet(parquet, index=False, engine="pyarrow")
    manifest = {
        "name": "smokesense_v1", "version": VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "build_seconds": round(time.time() - t0),
        "git_commit": git_commit(),
        "data_sha256": sha256(parquet),
        "pilot_events_sha256": sha256(CONFIG),
        "events": {e.event_id: {"tier": e.tier, "group_id": groups[e.event_id], "start": e.start_date,
                                "end": e.end_date, **info[e.event_id]} for e in events if e.event_id in info},
        "groups": {g: sorted(eid for eid in info if groups[eid] == g) for g in sorted(set(groups[e] for e in info))},
        **stats(df),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str) + "\n")
    print(f"wrote {len(df):,} rows to {parquet} ({manifest['build_seconds']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
