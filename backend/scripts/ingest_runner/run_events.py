"""Ingest every event in docs/pilot_events.json, one event per batch_ingest process.

Run from backend/ with POSTGRES_HOST/POSTGRES_PORT pointing at the DB:

    INGEST_PASS=fn   INGEST_SKIP=airnow,purpleair python scripts/ingest_runner/run_events.py
    INGEST_PASS=main INGEST_SKIP=purpleair        python scripts/ingest_runner/run_events.py

Every attempt passes --resume, so sources already marked success are skipped
(on a fresh DB nothing is). A failed event is retried at most twice more, then
the runner moves on. Each pass writes, under data/ingest_runs/ (gitignored):
ingest_<pass>.log (keys and passwords redacted), summary_<pass>.json (attempts,
seconds, HTTP requests per host) and data/ingest_reports/<pass>/<event>.json
(batch_ingest's coverage report). Events already ok in the summary are skipped,
so a pass can be restarted.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
PASS = os.environ.get("INGEST_PASS", "main")
SKIP = [s for s in os.environ.get("INGEST_SKIP", "purpleair").split(",") if s]
RUNS = BACKEND / "data" / "ingest_runs"
LOG, SUMMARY = RUNS / f"ingest_{PASS}.log", RUNS / f"summary_{PASS}.json"
REPORTS = BACKEND / "data" / "ingest_reports" / PASS
MAX_ATTEMPTS = 3  # the first run, then at most two retries

sys.path.insert(0, str(BACKEND))
from ingestion.connectors._common import load_env  # noqa: E402

load_env()
SECRETS = [v for k, v in os.environ.items()
           if k.endswith(("_KEY", "_PASSWORD", "_TOKEN")) and v and len(v) >= 6]


def redact(line):
    for s in SECRETS:
        line = line.replace(s, "[REDACTED]")
    return line


def main():
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONPATH=str(BACKEND))
    events = [e["event_id"] for e in json.loads((BACKEND / "docs/pilot_events.json").read_text())["events"]]
    RUNS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    summary = json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}
    with LOG.open("a") as log:
        for eid in events:
            if summary.get(eid, {}).get("ok"):
                continue
            rec = {"attempts": [], "requests": {}, "ok": False}
            t0 = time.time()
            for attempt in range(MAX_ATTEMPTS):
                args = ["--event", eid, "--resume", *[a for s in SKIP for a in ("--skip-source", s)],
                        "--report-out", str(REPORTS / f"{eid}.json")]
                log.write(f"\n===== {eid} attempt {attempt + 1} {time.strftime('%H:%M:%S')}\n")
                log.flush()
                p = subprocess.Popen([sys.executable, str(HERE / "child.py"), *args], cwd=BACKEND, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in p.stdout:
                    line = redact(line)
                    if line.startswith("REQUESTS "):
                        for host, n in json.loads(line[9:]).items():
                            rec["requests"][host] = rec["requests"].get(host, 0) + n
                    log.write(line)
                    log.flush()
                rc = p.wait()
                rec["attempts"].append(rc)
                if rc == 0:
                    rec["ok"] = True
                    break
            rec["seconds"] = round(time.time() - t0)
            summary[eid] = rec
            SUMMARY.write_text(json.dumps(summary, indent=1))
            log.write(f"===== {eid} done ok={rec['ok']} attempts={rec['attempts']} "
                      f"{rec['seconds']}s requests={rec['requests']}\n")
            log.flush()
    print("ALL DONE")


if __name__ == "__main__":
    main()
