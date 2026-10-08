# Pilot-event verification scripts (rescued, not reproducible yet)

These scripts produced the pilot-event verification table in PR #26
(`docs/pilot-events.md` "Measured 2026-10-06" section and the
`verification_note` fields in `backend/docs/pilot_events.json`). They were
written as one-off scratch code and are copied here as-is so they are not lost.

**Status: not reproducible yet; refactor pending.** Do not run them from this
directory expecting the PR #26 numbers back: the hardcoded paths, missing
intermediate files and import issues below have to be fixed first.

API keys are read from the environment (`FIRMS_MAP_KEY`, `AIRNOW_API_KEY`, the
same names the connectors use); none are stored in these files.

## Run order

```
events -> stage1 -> stage2 -> item2 / item3 / item5 -> build
```

`events.py` is a data module (imported, not run). Caveat on the order:
`item5.py` reads `verdicts.json`, which `build.py` writes, so as the code stands
item5 needs a `build` run before it. `build.py` itself reads only
`stage1.json` and `stage2.json`; no script consumes `item2.json`,
`item3.json` or `item5.json`.

## Scripts: inputs and outputs

All paths are relative to this directory (`HERE = Path(__file__).parent`)
unless noted.

| Script | Reads | Writes |
|---|---|---|
| `events.py` | (none; pilot events as they stood in `docs/pilot-events.md` on dev, 2026-10-06) | (none; imported as `EVENTS`, `products_for`) |
| `firms_pull.py` | FIRMS API (`FIRMS_MAP_KEY`) via `ingestion.connectors.firms` | `firms_cache/<hash>.json` (cache) |
| `stage1.py` | `ca_counties.json`, `events.py`, FIRMS via `firms_pull` | `stage1.json` (fire-centred bboxes) |
| `stage2.py` | `stage1.json`, FIRMS via `firms_pull`, AirNow API (`AIRNOW_API_KEY`) via `ingestion.connectors.airnow` | `airnow_cache/*.json` (cache), `stage2.json` |
| `hourly.py` | AirNow rows via `stage2`; imports `airnow_time_offsets` (see below) | (none; helper module) |
| `item2.py` | `stage2.json`, `hourly`, `stage1` | `item2.json` (missing hours vs peak-smoke days) |
| `item3.py` | `stage2.json`, `hourly`, `events.py` | `item3.json` (peak daily mean PM2.5, LST days, >= 18 h) |
| `item5.py` | `stage2.json`, `verdicts.json`, FIRMS via `firms_pull` | `item5.json` (share of FIRMS FRP outside the event bbox) |
| `build.py` | `stage1.json`, `stage2.json`, `events.py` | `verdicts.json`, `entries.json`, `doc_table.md` |
| `aqs_check.py` | `stage2.json`, `item2.json`, `airdata/ca_hourly_<param>_<year>.csv` | (prints; AQS vs AirNow side check for PE-008, PE-011, PE-004 Paradise; not part of the main chain) |

Committed outputs: `verdicts.json`, `entries.json`, `doc_table.md`, `item4.json`.

**`item4.json` has no producer script.** No `item4.py` survived; the file
holds only `[]`.

## Not included

Left out of the repo on purpose (kept in a local backup outside the repo):
raw data and caches (`airdata/`, `firms_cache/`, `airnow_cache/`,
`airnow_cache_mt/`), intermediates (`stage1.json`, `stage2.json`,
`item2.json`, `item3.json`, `item5.json`), small inputs (`ca_counties.json`,
`crews.json`), PR bodies, and the scratch copy of `airnow_time_offsets.py`
(byte-identical to `backend/ingestion/connectors/airnow_time_offsets.py`).

## Known issues for the refactor

- Hardcoded absolute paths:
  - `firms_pull.py:7`: `sys.path.insert(0, "/Users/trungdinh30/SmokeSense-wildfire-smoke-prediction/backend")`
  - `stage2.py:9`: same `sys.path.insert`
- Other scripts reach `ingestion.*` only because importing `stage2` or
  `firms_pull` inserts that absolute path first.
- `hourly.py:14` does `from airnow_time_offsets import ...`, which expected
  the scratch copy beside it; it should import
  `ingestion.connectors.airnow_time_offsets` instead.
- `stage1.py` needs `ca_counties.json`, which is not committed.
