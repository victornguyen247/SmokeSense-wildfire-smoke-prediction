"""Compare a reproduced DATA-04 run with the canonical artifacts; exit 1 on any mismatch.

    python scripts/compare_repro.py <repro_dir>

Checks: dataset sha256 against data/datasets/smokesense_v1/manifest.json; metrics.json of
baseline_v1 and baseline_v2 (every number, to 1e-9), release.json and thresholds.json against
data/models/<name>/. Then prints the headline table.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CANON_DATA = BACKEND / "data" / "datasets" / "smokesense_v1" / "manifest.json"
CANON_MODELS = BACKEND / "data" / "models"


def diff(a, b, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = [f"{path}/{k}: missing" for k in set(a) ^ set(b)]
        return out + [d for k in set(a) & set(b) for d in diff(a[k], b[k], f"{path}/{k}")]
    if isinstance(a, list) and isinstance(b, list):
        return [f"{path}: length"] if len(a) != len(b) else [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, f"{path}[{i}]")]
    if isinstance(a, float) and isinstance(b, float):
        same = (math.isnan(a) and math.isnan(b)) or math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
        return [] if same else [f"{path}: {a} != {b}"]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def main(repro: Path) -> int:
    problems = []
    want = json.loads(CANON_DATA.read_text())["data_sha256"]
    got = json.loads((repro / "dataset" / "manifest.json").read_text())["data_sha256"]
    print(f"dataset sha256: {'match' if got == want else 'MISMATCH'} ({got[:16]})")
    if got != want:
        problems.append("dataset sha256")
    for name, files in (("baseline_v1", ["metrics.json"]), ("baseline_v2", ["metrics.json", "release.json", "thresholds.json"])):
        for f in files:
            d = diff(json.loads((CANON_MODELS / name / f).read_text()), json.loads((repro / name / f).read_text()))
            print(f"{name}/{f}: {'match' if not d else f'{len(d)} differences, e.g. {d[:3]}'}")
            problems += [f"{name}/{f}"] if d else []
    m1 = json.loads((repro / "baseline_v1" / "metrics.json").read_text())["persistence_rows"]
    m2 = json.loads((repro / "baseline_v2" / "metrics.json").read_text())["persistence_rows"]
    rel = json.loads((repro / "baseline_v2" / "release.json").read_text())
    print("\nMAE on persistence rows   persistence      v1      v2   serves")
    print(f"  pooled                  {m2['persistence']['pooled']['mae']:>11.2f} {m1['xgb_d4']['pooled']['mae']:>7.2f} {m2['v2']['pooled']['mae']:>7.2f}")
    for h in ("1", "3", "6", "12", "24"):
        print(f"  {h:>3} h                   {m2['persistence']['by_horizon_hours'][h]['mae']:>11.2f} "
              f"{m1['xgb_d4']['by_horizon_hours'][h]['mae']:>7.2f} {m2['v2']['by_horizon_hours'][h]['mae']:>7.2f}   {rel[h]['serve']}")
    print("\nREPRODUCED" if not problems else f"\nMISMATCH: {', '.join(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
