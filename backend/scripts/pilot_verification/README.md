# Pilot-event verification scripts

These scripts produced the pilot-event verification table in PR #26: the
"Measured 2026-10-06" section of `docs/pilot-events.md` and the
`verification_note` fields in `backend/docs/pilot_events.json`. They began as
one-off scratch code. They have had only the minimal edits needed to run from
the repo, not a full refactor.

API keys come from the environment through
`ingestion.connectors._common.load_env()`, using the same names the connectors
use (`FIRMS_MAP_KEY`, `AIRNOW_API_KEY`). Keys are needed only on a cache miss,
and these files store none.

## Running

From `backend/` with the backend virtualenv:

```
python scripts/pilot_verification/run_all.py                       # all 20 events
python scripts/pilot_verification/run_all.py --only PE-001 PE-004  # a subset
python scripts/pilot_verification/run_all.py --offline             # cache only, no API calls
```

`run_all.py` runs `stage1 -> stage2 -> item2, item3, item5 -> build`, each step
as its own process. With `--offline`, any request missing from the cache
raises `CacheMiss`, which names the cache file, and the run stops. Nothing
calls an API in that mode.

| Setting | Meaning |
|---|---|
| `PILOT_VERIFY_CACHE` | Cache root holding `firms_cache/`, `airnow_cache/` and `airdata/`. Default: `.cache/` in this folder (gitignored). |
| `PILOT_VERIFY_OFFLINE=1` | Set by `--offline`. |
| `out/` | Generated outputs (gitignored). |

`--only` merges the named events into the files already in `out/`. Without
`--only`, `item5.py` keeps any event already in `out/item5.json`, so it can
resume an interrupted run. Delete `out/` for a clean full run.

## Known gap: PE-001 bbox

`reference/stage1.json` has PE-001's bbox widened east-west by hand
(`bbox_adjust`: "widened E-W (symmetrically) to include Willows-Colusa, 18.9
km from the fire"), giving -123.86..-122.13 (148 km wide). `stage1.py` does
not do this widening, so it produces -123.71..-122.28 (122 km), which has no
AirNow site inside. Offline, that narrower box misses the cache at
`item2.py`, so PE-001 is not reproducible until the widening is encoded or
dropped. That decision is still open.

## Scripts: inputs and outputs

| Script | Reads | Writes |
|---|---|---|
| `paths.py` | env (above) | (none; shared paths, `CacheMiss`) |
| `events.py` | (none; pilot events as they stood in `docs/pilot-events.md` on dev, 2026-10-06) | (none; imported as `EVENTS`, `products_for`) |
| `firms_pull.py` | FIRMS API via `ingestion.connectors.firms` | `firms_cache/<md5>.json` |
| `stage1.py` | `ca_counties.json`, `events.py`, FIRMS via `firms_pull` | `out/stage1.json` (fire-centred bboxes) |
| `stage2.py` | `out/stage1.json`, FIRMS, AirNow API via `ingestion.connectors.airnow` | `airnow_cache/*.json`, `out/stage2.json` |
| `hourly.py` | AirNow rows via `stage2.airnow` | (none; helper) |
| `item2.py` | `out/stage2.json`, `hourly`, `stage1` | `out/item2.json` (missing hours vs peak-smoke days, sites < 90%) |
| `item3.py` | `out/stage2.json`, `hourly`, `events.py` | `out/item3.json` (peak daily mean PM2.5, LST days, ≥ 18 h; tier via `TIER_RANGES`) |
| `item5.py` | `out/stage2.json`, `build.verdict()`, FIRMS | `out/item5.json` (share of FRP within 200 km of each in-bbox site that is outside the bbox) |
| `build.py` | `out/stage1.json`, `out/stage2.json`, `out/item3.json`, `out/item5.json` | `out/verdicts.json`, `out/entries.json`, `out/doc_table.md` |
| `aqs_check.py` | `out/stage2.json`, `out/item2.json`, `airdata/ca_hourly_<param>_<year>.csv` | (prints; AQS vs AirNow side check for PE-004 Paradise; not in `run_all`) |
| `run_all.py` | (runs the chain) | |

`doc_table.md` has two parts:
- The rows of the measured table in `docs/pilot-events.md`, in the same 7 columns and format.
- A separate table of item5's outside-bbox FRP and detection shares. The doc's table has no column for those.

AirNow time offsets: `normalize_airnow_row` applies
`ingestion/connectors/airnow_time_offsets.py` (on dev since PR #27), so
`hourly.py` uses `valid_at` as given and does not shift again.

## Committed files

- `ca_counties.json`: county bboxes used by `stage1.py`.
- `crews.json`: data from the Crews Fire check (PR #21's PE-020 replacement). No script reads it.
- `reference/`: the PR #26 snapshot, which is the outputs as they were when #26 was written: `stage1`, `stage2`, `item2`, `item3`, `item5`, `verdicts`, `entries` `.json`, plus `doc_table.md`. Its `doc_table.md` and `entries.json` predate the item3 and item5 columns, so they say "Pending".
- `item4.json` was removed. It held only `[]`, and no `item4.py` survived to produce it.

Raw data and caches are not committed. `airdata/` (1.1 GB), `firms_cache/` (913 MB) and `airnow_cache/` (25 MB) are kept in a local backup outside the repo. Point `PILOT_VERIFY_CACHE` at a copy of them to run offline.
