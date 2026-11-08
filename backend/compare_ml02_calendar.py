
import numpy as np
import pandas as pd
import xgboost as xgb

import evaluate_ml02_rolling as r

PATH = "data/datasets/smokesense_v1.1/data.parquet"
THRESHOLD = 35.5
HORIZON = 12

df = pd.read_parquet(PATH)
df["issue_time"] = pd.to_datetime(df["issue_time"], utc=True)
df["target_time"] = pd.to_datetime(df["target_time"], utc=True)

configs = {
    "full": list(r.FEATURES),
    "no_day": [f for f in r.FEATURES if f != "day_of_year"],
}

results = []

for fold, start in enumerate(r.TEST_STARTS, 1):
    test_start = pd.Timestamp(start, tz="UTC")
    valid_start = test_start - pd.Timedelta(days=r.VALID_DAYS)

    # Earlier chronological data, separated from validation labels
    pretrain = df[
        (df["target_time"] < valid_start)
        & (df["horizon_hours"] == HORIZON)
    ].copy()

    evaluation = df[
        (df["issue_time"] >= valid_start)
        & (df["target_time"] < test_start)
        & (df["horizon_hours"] == HORIZON)
    ].copy()

    # Inner chronological split for early stopping.
    times = np.sort(pretrain["issue_time"].unique())
    inner_start = pd.Timestamp(
        times[int(len(times) * 0.8)]
    )

    train = pretrain[pretrain["target_time"] < inner_start]
    inner_valid = pretrain[
        (pretrain["issue_time"] >= inner_start)
        & (pretrain["target_time"] < valid_start)
    ]

    if min(len(train), len(inner_valid), len(evaluation)) == 0:
        raise ValueError(f"Empty partition in fold {fold}")

    y = evaluation[r.TARGET].to_numpy(float)

    for name, features in configs.items():
        x_train = r.mat(train)[features]
        x_inner = r.mat(inner_valid)[features]
        x_eval = r.mat(evaluation)[features]

        dtrain = xgb.DMatrix(
            x_train,
            label=np.log1p(train[r.TARGET].to_numpy(float)),
        )
        dinner = xgb.DMatrix(
            x_inner,
            label=np.log1p(inner_valid[r.TARGET].to_numpy(float)),
        )

        model = xgb.train(
            r.PARAMS,
            dtrain,
            num_boost_round=r.N_ESTIMATORS,
            evals=[(dinner, "inner_validation")],
            early_stopping_rounds=r.EARLY_STOPPING,
            verbose_eval=False,
        )

        pred = np.clip(
            np.expm1(
                model.predict(
                    xgb.DMatrix(x_eval),
                    iteration_range=(0, model.best_iteration + 1),
                )
            ),
            0,
            None,
        )

        actual_high = y >= THRESHOLD
        predicted_high = pred >= THRESHOLD

        tp = int((actual_high & predicted_high).sum())
        fp = int((~actual_high & predicted_high).sum())
        fn = int((actual_high & ~predicted_high).sum())

        result = {
            "fold": fold,
            "config": name,
            "n": len(y),
            "rounds": model.best_iteration + 1,
            "mae": np.mean(np.abs(y - pred)),
            "rmse": np.sqrt(np.mean((y - pred) ** 2)),
            "bias": np.mean(pred - y),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "recall": tp / (tp + fn) if tp + fn else np.nan,
        }
        results.append(result)

out = pd.DataFrame(results)
print(out.round(3).to_string(index=False))

out.to_csv(
    "data/models/ml02_rolling_pe001/calendar_ablation.csv",
    index=False,
)
