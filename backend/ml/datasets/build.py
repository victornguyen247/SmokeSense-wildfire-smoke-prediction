"""Reproducible DATA-04 versioned Parquet export and manifest."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from ml.datasets.schema import cast_and_validate

_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assign_time_splits(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """PM-01 grouped holdout: keep every complete event in exactly one split.

    Event groups are ordered by their first issue_time (with ID tie-breaking).
    We never use random row splits, and assignment is reproducible regardless
    of input row order. With fewer than three events a 3-way holdout cannot
    be produced safely, so fail rather than splitting an event in half.
    """
    result = frame.sort_values(
        ["issue_time", "pilot_event_id", "forecast_point_id", "horizon_hours"],
        kind="stable",
    ).reset_index(drop=True)
    events = (
        result.groupby("pilot_event_id", sort=True, observed=True)["issue_time"]
        .min()
        .reset_index()
        .sort_values(["issue_time", "pilot_event_id"], kind="stable")
    )["pilot_event_id"].astype(str).tolist()
    if len(events) < 3:
        raise ValueError("Need at least 3 distinct pilot events for grouped train/val/test split")
    n = len(events)
    train_cut = min(max(1, int(n * 0.70)), n - 2)
    val_cut = min(max(train_cut + 1, int(n * 0.85)), n - 1)
    event_groups = {
        "train": events[:train_cut],
        "val": events[train_cut:val_cut],
        "test": events[val_cut:],
    }
    lookup = {event_id: split for split, ids in event_groups.items() for event_id in ids}
    result["split"] = result["pilot_event_id"].astype(str).map(lookup).astype("string")
    assert result["split"].notna().all(), "Every event must be assigned"
    counts = result["split"].value_counts().to_dict()
    return result, {
        "method": "chronological_group_holdout_by_pilot_event_id",
        "unit": "pilot_event_id",
        "events": event_groups,
        "event_counts": {name: len(ids) for name, ids in event_groups.items()},
        "counts": {k: int(counts.get(k, 0)) for k in ("train", "val", "test")},
        "note": "Events are disjoint between splits; overlapping event date ranges require ML-owner review",
    }


def _card_text(version: str, df: pd.DataFrame, info: dict) -> str:
    events = ", ".join(sorted(df["pilot_event_id"].unique().tolist()))
    features = ", ".join(col for col in df.columns if col not in {
        "forecast_point_id", "pilot_event_id", "issue_time", "target_time",
        "target_pm25", "target_source", "target_monitor_id", "split",
    })
    return f"""# SmokeSense DATA-04 Dataset Card — {version}

## Actual release metadata
- Rows: {len(df)}
- Issue-time date range (UTC): {df['issue_time'].min().isoformat()} → {df['issue_time'].max().isoformat()}
- Events: {events}
- Split counts: {info['counts']}
- Train/val/test grouped by entire event: {info['event_counts']}
- Event assignments: {info['events']}
- Feature columns: {features}

## Labels and known limitations (read before training)
- Target: `target_pm25` in µg/m³ at `target_time = issue_time + horizon_hours`.
- Contractual regulatory source: AirNow preliminary hourly **RawConcentration**;
  AQS values where they have been backfilled. `target_source` presently only
  identifies `regulatory`, NOT which individual rows were AirNow vs AQS.
  **A separate provenance/source column and verification are pending GEO-01/#22.**
- Red Bluff station **061030007** time offsets applied upstream. Lone Pine and
  Tahoe City offsets remain **unverified**.
- Some sites have missing observations on peak smoke days.
- Sites without an AQS counterpart have **unverified timing**.
- **No PurpleAir labels or fallback.** `purpleair_raw` must NEVER be a target.
- Weather uses NCEI observations measured at or before `issue_time`.
- Only past fire/PM2.5 data may form features; review upstream leakage controls.
- Each pilot event belongs to exactly one train/val/test split (PM-01).
  Event groups are ordered by their first issue time; the ML owner must
  review cross-event time overlap and the holdout selection before release.
- This dataset is experimental; it is not an official air-quality warning.

## Units
- `target_pm25` and `pm25_lag_*`: µg/m³
- Distance: km; temperature: °C; wind speed: m/s; precipitation: mm/hour;
  pressure: hPa; humidity: percent; angular bearings: degrees.
- `precip_prob_pct` must be null for v1 NCEI observed weather.

## Release checklist
- [ ] PM-01 exact fields/dtypes/units signed off (extra `split` and optional
      `target_monitor_id` currently need agreement)
- [ ] Final event list and coverage verified against real data
- [ ] AirNow vs AQS row-level provenance confirmed by GEO-01 owner
- [ ] ML owner reviews event-group split and label coverage
- [ ] Generated Parquet and manifest stored in shared Drive/S3, not committed
"""


def build_versioned_dataset(
    raw: pd.DataFrame, *, version: str, output_root: str | Path,
) -> Path:
    """Write a non-overwriting dataset directory with event partitions + hashes.

    Use `pd.read_parquet(output_dir / "data")` after installing pyarrow.
    `manifest.json` and `DATASET_CARD.md` remain at the version root; only
    the `data/` directory is a Parquet dataset (with event partitions).
    """
    if not _VERSION.fullmatch(version) or version in {".", ".."}:
        raise ValueError("Invalid version string")
    root = Path(output_root)
    final = root / f"training_{version}"
    if final.exists():
        raise FileExistsError(f"Dataset already exists: {final}")
    # Fast fail before creating any output folders.
    frame = cast_and_validate(raw)
    frame, split_details = assign_time_splits(frame)
    root.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".training_{version}_", dir=root))
    try:
        files = []
        for event_id, part in frame.groupby("pilot_event_id", sort=True):
            path = temp / "data" / f"event_id={quote(str(event_id), safe='')}" / "part-00000.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            part.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
            files.append({
                "path": str(path.relative_to(temp)).replace("\\", "/"),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "rows": len(part),
            })
        manifest = {
            "version": version,
            "format": "partitioned_parquet",
            "data_path": "data",
            "partition_directory": "event_id",
            "event_id_source_column": "pilot_event_id",
            "rows": len(frame),
            "events": sorted(frame["pilot_event_id"].unique().tolist()),
            "issue_time_min_utc": frame["issue_time"].min().isoformat(),
            "issue_time_max_utc": frame["issue_time"].max().isoformat(),
            "label": "target_pm25",
            "label_unit": "ug/m3",
            "label_source_allowed": ["regulatory"],
            "airnow_aqs_per_row_provenance": "pending_GEO01",
            "dtypes": {key: str(dtype) for key, dtype in frame.dtypes.items()},
            "splits": split_details,
            "files": files,
        }
        (temp / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        (temp / "DATASET_CARD.md").write_text(
            _card_text(version, frame, split_details), encoding="utf-8",
        )
        temp.rename(final)  # do not overwrite any existing version
        return final
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
