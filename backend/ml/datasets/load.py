"""Load a versioned DATA-04 dataset and verify it against its manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parents[2]
SMOKESENSE_V1 = BACKEND / "data" / "datasets" / "smokesense_v1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_dataset(folder: Path = SMOKESENSE_V1) -> tuple[pd.DataFrame, dict]:
    """(rows, manifest); raises if data.parquet does not match the manifest's sha256."""
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    got = sha256(folder / "data.parquet")
    if got != manifest["data_sha256"]:
        raise ValueError(f"{folder / 'data.parquet'} sha256 {got} != manifest {manifest['data_sha256']}")
    return pd.read_parquet(folder / "data.parquet"), manifest
