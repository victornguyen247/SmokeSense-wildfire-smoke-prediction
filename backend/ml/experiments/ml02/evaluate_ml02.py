"""Paired, exploratory evaluation of SmokeSense ML-02 methods A and B.

Run from the SmokeSense backend directory:
    python evaluate_ml02.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

PATH = Path('data/models/ml02_method_a_pe001/matched_predictions.parquet')
BOOTSTRAPS = 3000
SEED = 42


def evaluate_horizon(data: pd.DataFrame, rng: np.random.Generator) -> dict:
    truth = data['target_pm25'].to_numpy(dtype=float)
    pred_a = data['method_a_prediction'].to_numpy(dtype=float)
    pred_b = data['method_b_prediction'].to_numpy(dtype=float)
    ea = pred_a - truth
    eb = pred_b - truth
    paired_advantage = np.abs(ea) - np.abs(eb)  # positive: B has lower MAE
    dates = data['issue_time'].dt.floor('D')
    blocks = [np.flatnonzero(dates.to_numpy() == day) for day in dates.unique()]
    boot = np.empty(BOOTSTRAPS, dtype=float)
    for i in range(BOOTSTRAPS):
        sampled = rng.integers(0, len(blocks), size=len(blocks))
        idx = np.concatenate([blocks[j] for j in sampled])
        boot[i] = float(paired_advantage[idx].mean())
    lower, upper = np.quantile(boot, [0.025, 0.975])
    return {
        'horizon': int(data['horizon_hours'].iloc[0]),
        'n': len(data),
        'days': len(blocks),
        'mae_a': float(np.abs(ea).mean()),
        'mae_b': float(np.abs(eb).mean()),
        'rmse_a': float(np.sqrt(np.mean(ea**2))),
        'rmse_b': float(np.sqrt(np.mean(eb**2))),
        'bias_a': float(ea.mean()),
        'bias_b': float(eb.mean()),
        'mae_a_minus_b': float(paired_advantage.mean()),
        'ci_lower': float(lower),
        'ci_upper': float(upper),
    }


def main() -> None:
    d = pd.read_parquet(PATH)
    required = ['forecast_point_id', 'issue_time', 'horizon_hours',
                'target_pm25', 'method_a_prediction', 'method_b_prediction']
    missing = sorted(set(required) - set(d.columns))
    if missing:
        raise ValueError(f'Missing columns: {missing}')
    if d.duplicated(['forecast_point_id', 'issue_time', 'horizon_hours']).any():
        raise ValueError('Duplicate prediction keys: evaluation halted')
    d['issue_time'] = pd.to_datetime(d['issue_time'], utc=True)
    for col in ['target_pm25', 'method_a_prediction', 'method_b_prediction']:
        d[col] = pd.to_numeric(d[col], errors='coerce')
    if not np.isfinite(d[['target_pm25', 'method_a_prediction',
                          'method_b_prediction']].to_numpy(dtype=float)).all():
        raise ValueError('Missing or non-finite target/prediction values: evaluation halted')
    rng = np.random.default_rng(SEED)
    out = pd.DataFrame([evaluate_horizon(g, rng) for _, g in d.groupby('horizon_hours')])
    pd.set_option('display.width', 200)
    pd.set_option('display.max_columns', None)
    print('Positive MAE(A-B) = Method B better; 95% CI uses paired UTC-day block bootstrap.')
    print(out.round(3).to_string(index=False))
    if (out.days < 20).any():
        print('\nCAUTION: Fewer than 20 day-blocks for at least one horizon; CI may be unstable.')
    print('Exploratory single-event results; daily resampling does not establish spatial generalization.')
    output = Path('data/models/ml02_method_a_pe001/paired_evaluation.csv')
    out.to_csv(output, index=False)
    print(f'Saved {output}')


if __name__ == '__main__':
    main()
