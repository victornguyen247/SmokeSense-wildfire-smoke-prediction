"""ml.evaluation.ml01_vs_data04: ML-01's group split, reproduced exactly and leak-free."""

from __future__ import annotations

import pandas as pd
import pytest

from ml.datasets.load import SMOKESENSE_V1, load_dataset
from ml.evaluation.ml01_vs_data04 import CONFIG, chronological_groups, ml01_split

needs_dataset = pytest.mark.skipif(
    not (SMOKESENSE_V1 / "data.parquet").is_file(),
    reason="smokesense_v1 not downloaded (scripts/fetch_data04.sh)",
)


def synthetic(n_groups: int = 13) -> pd.DataFrame:
    """One row per group, first issue times in reverse name order."""
    times = pd.date_range("2016-01-01", periods=n_groups, freq="180D", tz="UTC")
    return pd.DataFrame(
        {"group_id": [f"G{i:02d}" for i in range(n_groups)][::-1], "issue_time": times}
    )


def test_split_is_chronological_nine_two_two():
    df = synthetic()
    split = ml01_split(df)
    assert chronological_groups(df) == [f"G{i:02d}" for i in range(13)][::-1]
    assert [len(split[p]) for p in ("train", "val", "test")] == [9, 2, 2]
    assert split["test"] == ["G01", "G00"]  # the two latest groups


def test_no_test_group_is_in_training_or_validation():
    split = ml01_split(synthetic())
    assert not set(split["test"]) & set(split["train"])
    assert not set(split["test"]) & set(split["val"])
    assert not set(split["train"]) & set(split["val"])
    assert not set(CONFIG["test_groups"]) & set(
        CONFIG["train_groups"] + CONFIG["val_groups"]
    )


@needs_dataset
def test_split_reproduces_ml01_groups_and_row_counts():
    df, _ = load_dataset()
    split = ml01_split(df)
    assert split["train"] == CONFIG["train_groups"]
    assert split["val"] == ["G-PE-017", "G-PE-009"]
    assert split["test"] == ["G-PE-018", "G-PE-004"]
    rows = {p: int(df["group_id"].isin(split[p]).sum()) for p in split}
    assert rows == {"train": 104_710, "val": 2_760, "test": 34_484}  # rows of any lag
    train_rows = df[df["group_id"].isin(split["train"])]
    assert not set(train_rows["group_id"]) & set(split["test"])
