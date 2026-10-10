"""Run the pilot verification chain: stage1 -> stage2 -> item2, item3, item5 -> build.

With PILOT_EVENTS=pr21 the chain ends with item6 instead of build: build.py
writes the PR #26 config entries and doc table, which are specific to that set.

    python run_all.py                      # all events
    python run_all.py --only PE-001 PE-004 # a subset (merged into existing out/ files)
    python run_all.py --offline            # fail on any cache miss instead of calling an API

Outputs land in PILOT_VERIFY_OUT (default out/); caches are read from PILOT_VERIFY_CACHE (default .cache/).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ["stage1.py", "stage2.py", "item2.py", "item3.py", "item5.py", "build.py"]
STEPS_PR21 = ["stage1.py", "stage2.py", "item2.py", "item3.py", "item5.py", "item6.py"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", metavar="EVENT_ID", help="event ids to (re)compute, e.g. PE-001")
    ap.add_argument("--offline", action="store_true", help="fail on any cache miss instead of calling an API")
    args = ap.parse_args()
    sys.path.insert(0, str(HERE))
    from paths import EVENT_SET, EVENTS
    unknown = sorted(set(args.only or []) - {e[0] for e in EVENTS})
    if unknown:
        ap.error(f"unknown event id(s): {', '.join(unknown)}")

    env = dict(os.environ)
    if args.offline:
        env["PILOT_VERIFY_OFFLINE"] = "1"
    for step in STEPS_PR21 if EVENT_SET == "pr21" else STEPS:
        cmd = [sys.executable, str(HERE / step)]
        if step != "build.py":  # build always rebuilds from whatever is in out/
            cmd += args.only or []
        print(f"\n### {step}", flush=True)
        if subprocess.run(cmd, cwd=HERE, env=env).returncode != 0:
            sys.exit(f"{step} failed (with --offline, a cache miss shows up as CacheMiss naming the file)")
    from paths import OUT
    print(f"\nDone: outputs in {OUT.name}/")


if __name__ == "__main__":
    main()
