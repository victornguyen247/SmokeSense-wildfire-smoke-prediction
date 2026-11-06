"""Pipeline knobs. Plain environment variables, like the rest of ingestion/ (never raise)."""

from __future__ import annotations

import os
from pathlib import Path

from ingestion.live.common import env_int

BACKEND = Path(__file__).resolve().parents[1]

# Stage implementation per stage: "stub", "real", or "package.module:callable".
# Changing these is the whole stub -> real swap (no code change).
STAGE_ENV = {
    "features": ("PIPELINE_FEATURES_STAGE", "stub"),
    "predict": ("PIPELINE_PREDICT_STAGE", "stub"),
    "interpolate": ("PIPELINE_INTERPOLATE_STAGE", "real"),
}

STUB_MODEL_KEY = "stub-persistence/v0"


def stage_choice(stage: str) -> str:
    env, default = STAGE_ENV[stage]
    return os.getenv(env, "").strip() or default


def run_minute() -> int:
    """Minute past the hour. After AirNow (:25) and NWS (:05) so the hour that just
    ended is published before the features read it."""
    return env_int("PIPELINE_MINUTE", 40, 0, 59)


def stale_after_minutes() -> int:
    """/meta forecast_stale_after_minutes: about two missed hourly cycles."""
    return env_int("PIPELINE_STALE_AFTER_MINUTES", 150, minimum=1)


def work_dir() -> Path:
    """Where stages hand DataFrames to each other (Parquet, one folder per run)."""
    return Path(os.getenv("PIPELINE_WORK_DIR", "").strip() or BACKEND / "data" / "pipeline")


def max_retries() -> int:
    return env_int("PIPELINE_STAGE_RETRIES", 2, minimum=0)


def retry_backoff_seconds() -> int:
    return env_int("PIPELINE_RETRY_BACKOFF_S", 20, minimum=1)
