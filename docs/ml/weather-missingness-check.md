# Weather missingness check: baseline_v2 vs live NWS data

**Verdict: HARMLESS.** The live NWS gap in `precip_1h_mm` and `pressure_hpa` missingness does not hurt `baseline_v2`. All 11 checks of the pre-set rule pass. Analysis only: no model or dataset change. Numbers: [`weather-missingness-check.json`](weather-missingness-check.json). Code: `backend/ml/evaluation/weather_missingness_check.py`. Decision #43.

## Method

The check re-runs `baseline_v2`'s leave-one-group-out CV (13 folds, 5 horizons) with the shipped recipe: `ml.models.xgb_v2.fit`, setting `max_depth 4, no weights` from `params.json`. Every fold is **trained on unmasked rows**, as in production, and the two features are masked **only in the held-out fold at prediction time**, which is what serving sees.

| Scenario | Held-out fold |
|---|---|
| baseline | no masking |
| A (hard ablation) | both features NaN on every row |
| B (live-like) | randomly chosen *present* values set to NaN until each feature reaches its live missing rate (precip 0.87, pressure 0.60), seeds 0–4. The extra fraction masked is `(target − current) / (1 − current)`: 0.685 of present precip values and 0.132 of present pressure values. |

- **Row set:** metrics are on the 139,020 persistence rows, where the residual model serves and the release rule is computed. The 2.1% of rows without persistence use the v1 fallback and are not scored here.
- **F1:** F1 ≥ 35.5 uses the shipped cut-offs from `release.json` (35.5 / 29.5 / 25.5 / 21.5 / 20.0). The model card's exceedance table uses per-fold cut-offs on all rows, so its F1 values differ slightly.
- **Imputation:** nothing is imputed; missing stays NaN.
- **Runtime:** about 15 s.

**Baseline reproduction:** pooled MAE v2 **11.40** vs persistence **12.31**, as in `docs/models/baseline_v2.md`. The out-of-fold predictions are identical to the shipped `oof_predictions.parquet` (maximum difference 0).

## Measured missing rates (smokesense_v1, 141,954 rows)

| Feature | Training (measured) | Figure we were given | Live NWS (first run) |
|---|---|---|---|
| `precip_1h_mm` | **58.7%** | 61% | 87% |
| `pressure_hpa` | **53.9%** | 57% | 60% |

The 61% and 57% figures were counted over every `weather_observations` row in the database, not over dataset rows. The dataset card's 58.71% / 53.91% are the right training figures.

Missingness in training is structural, not random. Groups G-PE-009, 015, 017, 018 and 020 have **100%** of both features missing, and G-PE-002 has 99% / 100%. G-PE-011 and 016 have 0%.

## Results (persistence rows)

Each table gives, per horizon: v2 MAE / persistence MAE / skill pooled / skill macro / F1 ≥ 35.5 at the shipped cut-off / bias on labels ≥ 125.5 µg/m³ (about 650 rows per horizon).

**Baseline** (serves v2 at 3, 6, 12, 24 h)

| Horizon | v2 MAE | Persistence MAE | Skill pooled | Skill macro | F1 | Bias ≥ 125.5 |
|---|---|---|---|---|---|---|
| 1 h | 8.007 | 7.58 | −0.057 | +0.061 | 0.813 | −83.4 |
| 3 h | 9.871 | 10.37 | +0.048 | +0.136 | 0.757 | −101.9 |
| 6 h | 11.743 | 12.82 | +0.084 | +0.174 | 0.694 | −127.2 |
| 12 h | 13.067 | 15.09 | +0.134 | +0.230 | 0.623 | −139.9 |
| 24 h | 14.350 | 15.74 | +0.088 | +0.110 | 0.573 | −143.0 |

**A: both features always missing** (serves v2 at 3, 6, 12, 24 h)

| Horizon | v2 MAE | Persistence MAE | Skill pooled | Skill macro | F1 | Bias ≥ 125.5 |
|---|---|---|---|---|---|---|
| 1 h | 7.951 | 7.58 | −0.050 | +0.062 | 0.814 | −82.5 |
| 3 h | 9.849 | 10.37 | +0.050 | +0.136 | 0.757 | −101.6 |
| 6 h | 11.723 | 12.82 | +0.086 | +0.175 | 0.694 | −127.0 |
| 12 h | 12.959 | 15.09 | +0.141 | +0.232 | 0.623 | −138.2 |
| 24 h | 14.342 | 15.74 | +0.089 | +0.110 | 0.573 | −142.6 |

**B: live-like, mean ± sd over seeds 0–4** (serves v2 at 3, 6, 12, 24 h for every seed)

| Horizon | v2 MAE | Persistence MAE | Skill pooled | Skill macro | F1 | Bias ≥ 125.5 |
|---|---|---|---|---|---|---|
| 1 h | 8.000 ± 0.001 | 7.58 | −0.056 | +0.061 | 0.813 ± 0.000 | −83.3 |
| 3 h | 9.867 ± 0.001 | 10.37 | +0.049 | +0.136 | 0.757 ± 0.000 | −101.9 |
| 6 h | 11.740 ± 0.000 | 12.82 | +0.084 | +0.174 | 0.694 ± 0.000 | −127.2 |
| 12 h | 13.050 ± 0.003 | 15.09 | +0.135 | +0.230 | 0.623 ± 0.000 | −139.7 |
| 24 h | 14.345 ± 0.001 | 15.74 | +0.089 | +0.110 | 0.573 ± 0.000 | −143.0 |

Even with both features always missing, v2's MAE does not rise; it falls slightly, by up to 0.11 at 12 h. With 13 groups this is noise around zero, not evidence that the features hurt. The served horizons and F1 do not change in any scenario.

## Feature importance (shipped residual models, gain share, rank of 27)

| Feature | Mean gain share | Mean rank | Rank at 1 / 3 / 6 / 12 / 24 h |
|---|---|---|---|
| `precip_1h_mm` | 0.000 | 25 | 25 / 25 / 25 / 25 / 23 |
| `pressure_hpa` | 0.019 | 18 | 23 / 24 / 17 / 13 / 10 |

v2 never splits on `precip_1h_mm`, so its live missing rate cannot change v2 at all. `pressure_hpa` matters a little, more at long horizons.

## Verdict

The rule was fixed in `CONFIG` before the run. The gap is harmless only if, under B, every one of these holds:

- pooled v2 MAE rises by ≤ 0.15 µg/m³ at every horizon (mean over seeds);
- the release rule serves the same horizons (for every seed);
- F1 at 35.5 changes by ≤ 0.01 at every horizon (mean over seeds).

All 11 checks pass, so the gap is **HARMLESS**.

## Recommendation: what ML-04 shadow evaluation should monitor

- **Live missing rates** of `pressure_hpa` and `precip_1h_mm` per day. Re-run this check if pressure goes well beyond 60%: it is the feature v2 uses, ranked 10th at 24 h. A drift in precipitation alone is irrelevant to v2.
- **Structured missingness.** This check masked at random. Live gaps are by station (e.g. KLHM and KMYV had no reports). Compare live 12 h and 24 h MAE at points whose nearest station never reports pressure against points whose station does.
- **Anything that changes which station is nearest.** `wind_*`, `temp_c` and `rh_pct` are not covered by this check.
- **A retrained model.** A v2.1 trained on different weather data could start relying on precipitation. Re-run `python -m ml.evaluation.weather_missingness_check` for any retrained model before release.
