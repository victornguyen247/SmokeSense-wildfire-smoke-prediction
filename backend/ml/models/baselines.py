"""Baselines (docs/data-decisions.md #24): persistence and climatology."""
from __future__ import annotations

import numpy as np
import pandas as pd


def persistence(frame: pd.DataFrame) -> pd.Series:
    """The last observed PM2.5: pm25_lag_1h, falling back to lag_3h, then lag_6h; NaN if none."""
    return frame["pm25_lag_1h"].fillna(frame["pm25_lag_3h"]).fillna(frame["pm25_lag_6h"]).astype(float)


class Climatology:
    """Median label per (horizon, local solar hour, floored), fitted on training rows only."""

    def fit(self, frame: pd.DataFrame, target: str = "target_pm25") -> "Climatology":
        f = frame.assign(_hour=np.floor(frame["local_solar_hour"]).astype(int))
        self.table = f.groupby(["horizon_hours", "_hour"])[target].median().to_dict()
        self.by_horizon = f.groupby("horizon_hours")[target].median().to_dict()
        self.overall = float(f[target].median())
        return self

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        hours = np.floor(frame["local_solar_hour"]).astype(int)
        vals = [self.table.get((h, s), self.by_horizon.get(h, self.overall))
                for h, s in zip(frame["horizon_hours"], hours)]
        return pd.Series(vals, index=frame.index, dtype=float)

    def to_dict(self) -> dict:
        return {"table": {f"{h}|{s}": v for (h, s), v in self.table.items()},
                "by_horizon": {str(h): v for h, v in self.by_horizon.items()}, "overall": self.overall}
