"""Inference adapter (ML-04, #45): the PM-03 model interface over ml.inference.predict_v2.

    svc = InferenceService.from_registry(registry, name="baseline")         # production version
    svc = InferenceService.from_registry(registry, model_key="baseline/v1")  # an explicit version
    svc = InferenceService.from_dir(path, model_key="baseline/v2")          # a local folder (tests)
    rows = svc.predict(features)

`registry` is an mlops.registry.Registry built by the caller (mlops.registry.build_registry
reads app settings, and ml/ never imports app/). Swapping models means passing another
model_key; nothing else changes.

In: one row per Stage A forecast point, with forecast_point_id, issued_at (UTC) and the
input columns of the model's features.json, in that order (docs/ml/serving-contract.md §5).
Missing or misordered columns raise FeatureFrameError; extra columns are dropped with a
warning. Out: one row per (point, horizon) with the FORECAST_COLUMNS below. Rows whose
prediction is NaN are not returned.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.feature_columns import DERIVED
from ml.inference import predict_v2

log = logging.getLogger(__name__)

HORIZONS = predict_v2.HORIZONS
KEY_COLUMNS = ["forecast_point_id", "issued_at"]
FORECAST_COLUMNS = [
    "forecast_point_id",
    "horizon_hours",
    "pm25_predicted",
    "source",
    "model_key",
    "issued_at",
    "target_time",
]
SERVE_VALUES = {"v2", "persistence"}  # what predict_v2 serves; anything else is refused
NOT_INPUTS = {"horizon_hours", *DERIVED}  # set inside predict_v2, never by the caller


class FeatureFrameError(ValueError):
    """The input frame does not match the model's features.json."""


class ModelDirError(ValueError):
    """The model folder cannot be served by predict_v2."""


def input_columns(model_dir: Path) -> list[str]:
    """The columns the caller supplies: features.json minus horizon_hours and derived ones."""
    features = json.loads((model_dir / "features.json").read_text()).get("features")
    if not features:
        raise ModelDirError(f"{model_dir}/features.json has no 'features' list")
    return [c for c in features if c not in NOT_INPUTS]


def check_model_dir(model_dir: Path) -> None:
    """Every horizon must have a servable release.json entry and its boosters."""
    release = predict_v2.load_release(str(model_dir))
    for h in HORIZONS:
        rule = release.get(str(h))
        if not rule or rule.get("serve") not in SERVE_VALUES:
            raise ModelDirError(
                f"{model_dir}/release.json: {h} h serves {rule and rule.get('serve')!r}"
            )
        needed = [f"fallback_h{h}.json"] + (
            [f"model_h{h}.json"] if rule["serve"] == "v2" else []
        )
        missing = [n for n in needed if not (model_dir / n).is_file()]
        if missing:
            raise ModelDirError(f"{model_dir} is missing {missing}")


@dataclass(frozen=True)
class InferenceService:
    model_key: str
    model_dir: Path
    input_columns: tuple[str, ...]

    @classmethod
    def from_dir(cls, model_dir: Path | str, model_key: str) -> InferenceService:
        model_dir = Path(model_dir)
        check_model_dir(model_dir)
        return cls(model_key, model_dir, tuple(input_columns(model_dir)))

    @classmethod
    def from_registry(
        cls, registry: Any, name: str | None = None, model_key: str | None = None
    ) -> InferenceService:
        """The production version of `name`, or exactly `model_key` (verified by the registry)."""
        if (name is None) == (model_key is None):
            raise ValueError("pass exactly one of name or model_key")
        if model_key is not None:
            version = registry.get(model_key)
            path = registry.materialize(version)
        else:
            version, path = registry.load_production(name)
        return cls.from_dir(path, version.model_key)

    def validate(self, features: pd.DataFrame) -> pd.DataFrame:
        """features restricted to KEY_COLUMNS + input_columns, issued_at as UTC."""
        columns = list(features.columns)
        dupes = sorted({c for c in columns if columns.count(c) > 1})
        if dupes:
            raise FeatureFrameError(f"duplicate columns: {dupes}")
        wanted = [*KEY_COLUMNS, *self.input_columns]
        missing = [c for c in wanted if c not in columns]
        if missing:
            raise FeatureFrameError(f"missing columns: {missing}")
        extra = [c for c in columns if c not in wanted]
        if extra:
            log.warning(
                "dropping %d columns not in features.json: %s", len(extra), extra
            )
        got = [c for c in columns if c in self.input_columns]
        if got != list(self.input_columns):
            wrong = [
                f"{i}: {g} (expected {w})"
                for i, (g, w) in enumerate(zip(got, self.input_columns))
                if g != w
            ]
            raise FeatureFrameError(f"columns out of features.json order at {wrong}")
        issued = pd.to_datetime(features["issued_at"])
        if issued.dt.tz is None:
            raise FeatureFrameError("issued_at must be timezone-aware UTC")
        return features[wanted].assign(issued_at=issued.dt.tz_convert("UTC"))

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        """One row per (point, horizon) in FORECAST_COLUMNS; release.json decides v2 or persistence."""
        frame = self.validate(features).reset_index(drop=True)
        x = frame[list(self.input_columns)]
        parts = []
        for h in HORIZONS:
            out = predict_v2.predict(x, h, self.model_dir)
            parts.append(
                pd.DataFrame(
                    {
                        "forecast_point_id": frame["forecast_point_id"],
                        "horizon_hours": h,
                        "pm25_predicted": np.clip(out["pm25"].to_numpy(float), 0, None),
                        "source": out["source"].astype(str),
                        "model_key": self.model_key,
                        "issued_at": frame["issued_at"],
                        "target_time": frame["issued_at"] + pd.Timedelta(hours=h),
                    }
                )
            )
        rows = pd.concat(parts, ignore_index=True)[FORECAST_COLUMNS]
        return rows[rows["pm25_predicted"].notna()].reset_index(drop=True)
