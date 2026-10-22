---
paths:
  - "backend/ml/**"
  - "backend/features/**"
  - "backend/dataset_build/**"
  - "backend/ingestion/**"
  - "backend/shared/**"
---
# ML / data invariants

- `ml/` and `features/` must not import from `app/`. Lift shared code into `shared/` or pass plain arguments.
- Splits are time-based and leave-one-group-out on `group_id` (overlapping events share a group). `shuffle=True` or a random `train_test_split` is a bug.
- Features must be known at issue time and available to live inference. Never add labels, ids, coordinates, `event_tier`, `precip_prob_pct`.
- Fire features: VIIRS SNPP only (`_SP` in training, NRT live). PurpleAir is deferred to v1.1.
- Compare every model with persistence and climatology; report MAE/RMSE per horizon plus exceedance P/R/F1 at ≥35.5 µg/m³.
- Fix seeds (42); record dataset sha256 + git commit in the model manifest. Never commit model binaries.
- Normalize timestamps to UTC at ingestion; normalize AirNow AQS codes to 9 digits (`normalize_aqs_code`).
- Output framing: predictions are estimates with uncertainty, never official guidance.
- Locked choices live in `docs/data-decisions.md` (#1–#33); change one by adding a new dated entry, not by silently diverging.
