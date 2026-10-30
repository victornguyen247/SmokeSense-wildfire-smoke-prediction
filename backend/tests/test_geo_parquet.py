"""Opt-in acceptance check against the actual DATA-04 artifact and historical DB."""
import os
from pathlib import Path

import pytest


def test_monitor_features_match_v1_parquet():
    artifact = os.getenv("GEO03_PARQUET_PATH")
    if not artifact:
        pytest.skip("Set GEO03_PARQUET_PATH and configure the historical DB for real Parquet parity")
    from scripts.check_geo03 import parity

    parity(Path(artifact), samples=5)
