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
    """Global chronological split; purge targets crossing later split boundaries."""
    result = frame.sort_values(
        ["issue_time", "pilot_event_id", "forecast_point_id", "horizon_hours"],
        kind="stable",
    ).reset_index(drop=True)
    times = result["issue_time"].drop_duplicates().sort_values().reset_index(drop=True)
    if len(times) < 3:
        raise ValueError("Need >=3 distinct issue times for train/val/test")
    train_cut = max(1, int(len(times) * 0.70))
    val_cut = max(train_cut + 1, int(len(times) * 0.85))
    val_cut = min(val_cut, len(times) - 1)
    val_start = times.iloc[train_cut]
    test_start = times.iloc[val_cut]
    result["split"] = "train"
    result.loc[result["issue_time"] >= val_start, "split"] = "val"
    result.loc[result["issue_time"] >= test_start, "split"] = "test"
    # Any previous split sample whose label looks ahead into the next split leaks.
    leaked = (
        ((result["split"] == "train") & (result["target_time"] >= val_start)) |
        ((result["split"] == "val") & (result["target_time"] >= test_start))
    )
    removed = int(leaked.sum())
    result = result.loc[~leaked].copy()
    counts = result["split"].value_counts().to_dict()
    if any(counts.get(split, 0) == 0 for split in ("train", "val", "test")):
        raise ValueError("A split became empty after target-horizon embargo; more dates required")
    return result, {
        "method": "global_chronological_issue_time_with_target_time_embargo",
        "validation_start_utc": val_start.isoformat(),
        "test_start_utc": test_start.isoformat(),
        "embargoed_rows": removed,
        "counts": {k: int(counts.get(k, 0)) for k in ("train", "val", "test")},
        "event_holdout": "not_configured_pending_ml_owner",
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
- Target-horizon embargo rows removed: {info['embargoed_rows']}
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
- Time split is chronological with target-horizon embargo. Additional complete
  event holdouts must be approved with the ML owner before final release.
- This dataset is experimental; it is not an official air-quality warning.

## Units
- `target_pm25` and `pm25_lag_*`: µg/m³
- Distance: km; temperature: °C; wind speed: m/s; precipitation: mm/hour;
  pressure: hPa; humidity: percent; angular bearings: degrees.
- `precip_prob_pct` is nullable when only observed weather is available.

## Release checklist
- [ ] PM-01 exact fields/dtypes/units signed off (extra `split` and optional
      `target_monitor_id` currently need agreement)
- [ ] Event list confirmed
- [ ] AirNow vs AQS row-level provenance confirmed by GEO-01 owner
- [ ] ML owner reviews event-level holdout and label coverage
- [ ] Generated Parquet and manifest stored in shared Drive/S3, not committed
"""


def build_versioned_dataset(
    raw: pd.DataFrame, *, version: str, output_root: str | Path,
) -> Path:
    """Write a non-overwriting dataset directory with event partitions + hashes.

    Use `pd.read_parquet(output_dir)` after installing pyarrow; one version is a
    logical dataset composed of event partitions, NOT one physical .parquet file.
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
            path = temp / f"event_id={quote(str(event_id), safe='')}" / "part-00000.parquet"
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
