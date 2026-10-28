# Model gate: baseline_v2 (ML-05, #46)

| | |
|---|---|
| Model | `baseline/v2` in the registry, packaged from `backend/data/models/baseline_v2/` ([model card](baseline_v2.md)) |
| Rollback | `baseline/v1`, registered and `retired` (serves persistence, decision #48) |
| Evidence | The 13-fold leave-one-group-out out-of-fold predictions in `baseline_v2/oof_predictions.parquet`, the card's numbers, and a registry run on a throwaway database (2026-10-28 UTC) |
| Decided | 2026-10-27 |

## Result

| # | Criterion (#46) | Result | Numbers |
|---|---|---|---|
| 1a | Beats persistence at 6 h on MAE | **Pass** | MAE 11.74 vs 12.82 (skill +0.084 pooled, +0.175 macro over groups) |
| 1b | Beats persistence at 6 h on exceedance recall (≥ 35.5) | **Pass, with the explanation below** | Recall 0.735 vs 0.682 at the shipped 25.5 cut-off. At a fixed 35.5 cut-off it loses (0.567). Precision drops (0.657 vs 0.683), so F1 is about level (0.694 vs 0.683). |
| 2 | `training_data_hash` matches the `smokesense_v1` manifest | **Pass** | `6799c4052b94549744446a38af36a1b028f43cbe58c8e1bf00ba64c2ea5f5230` in the dataset manifest, the model manifest and both registered rows |
| 3 | Reproducible with `backend/scripts/reproduce_data04.sh` | **Pass** (2026-10-12, re-run 2026-10-25 and 2026-10-26) | `REPRODUCED` each time, including after #85's historical-rows fix with live rows loaded. The artifacts being registered are byte-identical to the 2026-10-12 run's output. |

## 1. Against persistence at 6 h

The 6 h numbers are on persistence rows: 27,824 rows, 4,809 of them ≥ 35.5 µg/m³. Each model is scored as it is served, with the cut-off from `release.json`. Persistence alarms at 35.5.

| 6 h | MAE | Precision ≥ 35.5 | Recall ≥ 35.5 | F1 ≥ 35.5 |
|---|---|---|---|---|
| Persistence | 12.82 | **0.683** | 0.682 | 0.683 |
| v2, fixed 35.5 cut-off | 11.74 | 0.777 | 0.567 | 0.656 |
| **v2, shipped 25.5 cut-off** | **11.74** | 0.657 | **0.735** | **0.694** |

**MAE.** v2 beats persistence in all 13 held-out groups ([card](baseline_v2.md#per-group-persistence-rows-mae)), so the MAE result does not hinge on the 2020 group.

**Recall: where and why it does not beat persistence.**

- **Only with the lower cut-off.** v2 is anchored on persistence and pulls readings back toward levels it saw in training. That makes it conservative near 35.5: at the fixed 35.5 cut-off it misses more exceedances than persistence (recall 0.567). The served threshold of 25.5 is the median of the 13 fold cut-offs (decision #30). It buys recall with precision, so **v2's alert F1 is level with persistence, not better.** The card reaches the same conclusion with per-fold cut-offs on all rows (F1 0.686 vs 0.683).
- **Slightly optimistic.** Each fold's cut-off was tuned on its own training groups. The median of 13 cut-offs therefore carries some information from every group, including the one being scored. The strict per-fold figure from the card is recall 0.690 (P 0.682): still above persistence's 0.682, by a hair.
- **Pooled, not per group.** Per held-out group at 6 h, recall is higher than persistence in 5 groups and lower in 4. The other 4 groups (G-PE-015/017/018/020) have ≤ 5 positives, and both models score 0 there.

| Group (positives) | Persistence recall | v2 recall | False alarms (persistence / v2) |
|---|---|---|---|
| G-PE-001 (3,680) | 0.730 | **0.782** | 978 / 1,153 |
| G-PE-002 (311) | 0.669 | **0.752** | 103 / 207 |
| G-PE-003 (458) | 0.627 | **0.738** | 181 / 278 |
| G-PE-010 (81) | 0.173 | **0.185** | 68 / 73 |
| G-PE-004 (132) | **0.295** | 0.265 | 89 / 61 |
| G-PE-006 (66) | **0.288** | 0.273 | 47 / 43 |
| G-PE-009 (18) | **0.167** | 0.111 | 15 / 8 |
| G-PE-011 (36) | **0.472** | 0.389 | 14 / 10 |
| G-PE-016 (15) | **0.333** | 0.067 | 10 / 9 |

  The gain is in the three large, smoky groups (G-PE-001 2020, G-PE-002 Dixie + River, G-PE-003). In the small low-smoke groups, v2 alarms less than persistence and misses more of the few exceedances.
- **Severe smoke.** v2 still under-predicts the most extreme hours (bias −116 µg/m³ on the 2020 group's ≥ 125.5 hours vs −49 for persistence; [card](baseline_v2.md#the-2020-group-by-reading-band-g-pe-001-persistence-rows)). Those hours are far above every cut-off, so they barely affect recall, but the value shown on the map will be too low.

**Other horizons**, as served (persistence rows):

| Horizon | Serves | Cut-off | MAE persistence / v2 | Recall persistence / served | F1 persistence / served |
|---|---|---|---|---|---|
| 1 h | persistence | 35.5 | 7.58 / 8.01 | 0.826 / 0.826 | 0.826 / 0.826 |
| 3 h | v2 | 29.5 | 10.37 / 9.87 | 0.748 / 0.751 | 0.749 / 0.757 |
| 6 h | v2 | 25.5 | 12.82 / 11.74 | 0.682 / 0.735 | 0.683 / 0.694 |
| 12 h | v2 | 21.5 | 15.09 / 13.07 | 0.612 / 0.682 | 0.614 / 0.623 |
| 24 h | v2 | 20.0 | 15.74 / 14.35 | 0.571 / 0.687 | 0.574 / 0.573 |

At 1 h the release rule (decision #31) serves persistence, because v2's pooled MAE skill is −0.057. At 24 h F1 is level, and 7 of the 13 fold cut-offs sat on the grid floor of 20.0 (card).

To recompute (from `backend/`):

```python
import json, pandas as pd
oof = pd.read_parquet("data/models/baseline_v2/oof_predictions.parquet")
rel = json.load(open("data/models/baseline_v2/release.json"))
r = oof[oof.persistence.notna() & (oof.horizon_hours == 6)]
hit = r.target_pm25 >= 35.5
for name, alarm in (("persistence", r.persistence >= 35.5), ("v2", r.v2 >= rel["6"]["threshold"])):
    print(name, (hit & alarm).sum() / hit.sum())   # recall
```

## 2. Training data hash

`ml/tools/package_baseline_for_registry.py` stops unless the model manifest's `dataset.data_sha256` equals `data/datasets/smokesense_v1/manifest.json`, and that `data.parquet` hashes to it. `register` copies the value into `model_versions.training_data_hash`. On the throwaway database both `baseline/v1` and `baseline/v2` hold `6799c405…5230`, equal to the manifest.

## 3. Reproducibility

The original end-to-end run of `backend/scripts/reproduce_data04.sh` was `data/repro/20261012T181847` on 2026-10-12, which ended `REPRODUCED` in 254 s. The checks were: dataset sha256, v1 and v2 `metrics.json` (every number to 1e-9), `release.json` and `thresholds.json`. Since then:

- **Re-run for #85 on 2026-10-25 and 2026-10-26.** Each run used a throwaway database restored from the DATA-03 release dump, with live FIRMS, AirNow and NWS rows loaded from the test fixtures. Both ran after `dataset_build` was changed to read historical rows only (`3c6555e`, then `row_scope` in `6889d1a`), and both printed `REPRODUCED`: dataset sha256 `6799c405…` (141,954 rows), with both models' metrics matching. Sources: the two commit messages and the PR #85 description.
- `scripts/compare_repro.py data/repro/20261012T181847` still prints `REPRODUCED` (re-run 2026-10-27).
- The boosters and metadata that went into the package are byte-identical to the 2026-10-12 run's output (`cmp` on `model_h*.json`, `fallback_h*.json`, `metrics.json`, `release.json`, `thresholds.json`).

## Registry

```
$ python -m mlops.registry list --name baseline
baseline/v1                  retired     2026-10-28 03:28  2fbbcd82f702  file://<tmp>/store/baseline/v1.tar.gz
baseline/v2                  production  2026-10-28 03:28  947284aec89d  file://<tmp>/store/baseline/v2.tar.gz
```

The thresholds stored in `baseline/v2` are `{"1": 35.5, "3": 29.5, "6": 25.5, "12": 21.5, "24": 20.0}`. Each archive's sha256 equals its `artifact_sha256`, and a fresh extraction is byte-identical to the package. The run was on a throwaway local database and registry. Registering on the shared database is a separate step (`docs/mlops/registry.md`).

## Sign-off

| Criterion | |
|---|---|
| 1a MAE at 6 h | Pass |
| 1b Recall at 6 h | Pass with explanation: v2 beats persistence only at the lower shipped cut-off, F1 is level, and recall is lower in the small groups |
| 2 Training data hash | Pass |
| 3 Reproducible | Pass (2026-10-12 run; `REPRODUCED` again on 2026-10-25 and 2026-10-26 after #85) |

Sign-off: Tin
