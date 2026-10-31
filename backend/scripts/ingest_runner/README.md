# Ingest runner and QA

These scripts load the 20 pilot events from `backend/docs/pilot_events.json` into the local DB, then check the result. Run everything from `backend/`. Point the DB at the docker-compose Postgres from the host with `POSTGRES_HOST=localhost POSTGRES_PORT=5433`; `.env` stays untouched.

| Script | What it does |
|---|---|
| `run_events.py` | Runs `batch_ingest` once per event, through `child.py`. See [Ingest](#ingest). |
| `child.py` | Runs `batch_ingest.main()` and counts HTTP requests per host. |
| `airnow_health.py` | Probes AirNow `/aq/data/` with a tiny 1-hour query every 5 minutes, for at most 3 hours. Exits 0 on HTTP 200. |
| `ingest_qa.py` | Checks the DB against the config and the data rules, and writes `reports/ingest_qa.md`. See [QA](#qa). |

## Ingest

```
export POSTGRES_HOST=localhost POSTGRES_PORT=5433
INGEST_PASS=fn   INGEST_SKIP=airnow,purpleair python scripts/ingest_runner/run_events.py   # FIRMS + NCEI
python scripts/ingest_runner/airnow_health.py                                              # wait for AirNow
INGEST_PASS=main INGEST_SKIP=purpleair        python scripts/ingest_runner/run_events.py   # adds AirNow
```

How `run_events.py` runs each event:
- **`--resume` on every attempt,** so a source already marked `success` is not fetched again. On a fresh DB nothing is marked, so everything runs.
- **Retries:** a failed event gets at most two more attempts, then the runner moves on to the next event.
- **Restartable:** events already ok in the pass's summary are skipped.

What a pass writes (all gitignored):
- `data/ingest_runs/ingest_<pass>.log`, with keys and passwords redacted.
- `data/ingest_runs/summary_<pass>.json`: attempts, seconds, and HTTP requests per host.
- `data/ingest_reports/<pass>/<event>.json`: `batch_ingest`'s coverage report.

**Why two passes:** on 2026-10-11 AirNow returned HTTP 504 to every request for about 40 minutes. Ingesting FIRMS and NCEI first, then adding AirNow with `--resume`, gives the same DB as a single `--skip-source purpleair` run. PurpleAir is deferred to v1.1 (`docs/data-decisions.md` #12).

## QA

```
python scripts/ingest_runner/ingest_qa.py              # all checks
python scripts/ingest_runner/ingest_qa.py --no-airnow  # e, f, g only (DB without AirNow yet)
```

No table carries an event id, so each event's rows are selected by space and time:
- **AirNow:** the tight bbox, over the event's UTC days. (d) and (i) also cover the 24 h lead and tail.
- **NCEI:** `ncei_bbox` (bbox + 50 km), over `[ncei_start_date, end_date]`.
- **FIRMS:** `firms_bbox`, over `[firms_start_date, end_date]`.

The checks:
- **(a)** AirNow sites in the DB vs `airnow_monitors_nearby`.
- **(b)** Valid hours at the tier and best sites vs the verification note.
- **(c)** Red Bluff `061030007`: rows are stored at the label plus its time offset. This is checked against the raw rows cached by `scripts/pilot_verification`.
- **(d)** No `pm25` of −999 or below 0, over the whole AirNow window.
- **(e)** FIRMS rows sit inside `firms_bbox` × window, and every event has SNPP rows.
- **(f)** At least one NCEI station in bbox + 50 km, and the best station has ≥ 50% valid hours over the event window.
- **(g)** No PurpleAir rows.
- **(h)** AirNow rows shared by events with overlapping windows, per event pair.
- **(i)** AirNow lead and tail coverage at the tier site: % of hours with a value in the 24 h before the start and the 24 h after the end.
- **(j)** Monitor identity: every AirNow monitor id is the hash of a normalized 9-character AQS code, and no code maps to two monitors.

The report also lists in-box AirNow sites whose AQS state code is not 06.

The script makes no API calls.

## Run of 2026-10-11

The local DB was wiped first (`alembic downgrade base && alembic upgrade head`). Then all 20 events from the final config were loaded, without PurpleAir.

- **First attempt:** PE-001's FIRMS pull completed (280k rows). The AirNow step then hit AirNow's outage (HTTP 504 to every request from about 22:13 to 22:50), and the process was stopped. Its HTTP request count was not captured; the plan was 57 FIRMS requests.
- **Pass `fn`:** FIRMS and NCEI for all 20 events, ok on the first attempt.
- **Pass `main`:** AirNow for all 20 after `airnow_health.py` saw HTTP 200, ok on the first attempt.
- **Requests:** FIRMS 385 counted, plus PE-001's uncounted 57, which matches the 442 estimate. NCEI 98, AirNow 99 (the first attempt's AirNow retries are not counted). No FIRMS rate-limit retries.

`reports/ingest_qa.md` holds the QA result for this run.
