"""Screen the PE-016/PE-017 replacement candidates and pick one per role.

Reads the candidates' run (PILOT_EVENTS=candidates, PILOT_VERIFY_OUT=out_candidates)
and the final set's run (out_final) for the other events' windows and centroids.
A candidate passes when it passes every final rule (rules_final.py), its tier is
Low, and its window does not overlap another final event's window within 200 km.
Per role, the pick is: pass first, then the smallest nearest-site distance, then
the highest % hours, then the most recent start; the two roles use different fires.

Writes reports/candidates_check.md and out_candidates/screen.json.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import events_candidates as C
import events_final as F
import stage1
from rules_final import evaluate

OVERLAP_KM = 200.0
CAND, FINAL = HERE / "out_candidates", HERE / "out_final"
REPORT = HERE / "reports" / "candidates_check.md"


def load(d, name):
    return json.loads((d / name).read_text())


def overlaps(a0, a1, b0, b1):
    return a0 <= b1 and b0 <= a1


def main():
    S1c, S2c, I3c, I6c = (load(CAND, n) for n in ("stage1.json", "stage2.json", "item3.json", "item6.json"))
    S1f = load(FINAL, "stage1.json")
    finals = {e[0]: e for e in F.EVENTS if e[0] not in ("PE-016", "PE-017")}

    rows = []
    for eid, name, _, start, end, counties, anchor in C.EVENTS:
        ev = evaluate(S2c[eid], I3c.get(eid), I6c.get(eid))
        c = S1c[eid].get("cluster") or {"lat": anchor[0], "lon": anchor[1]}
        clash = []
        for fid, fe in finals.items():
            fc = (S1f.get(fid) or {}).get("cluster")
            if fc and overlaps(start, end, fe[3], fe[4]):
                d = stage1.hav(c["lat"], c["lon"], fc["lat"], fc["lon"])
                if d <= OVERLAP_KM:
                    clash.append(f"{fid} ({d:.0f} km)")
        rules = dict(ev["rules"], tier_low=ev["tier"] == "low", no_overlap=not clash)
        rows.append({"id": eid, "role": C.ROLE[eid], "fire": C.FIRE[eid], "name": name, "start": start, "end": end,
                     "rules": rules, "pass": all(v is not False for v in rules.values()), "clash": clash,
                     "tier": ev["tier"], "peak": ev["peak"], "tier_site": ev["tier_site_name"],
                     "near_km": ev["nearest"]["dist_fire_km"] if ev["nearest"] else None,
                     "near_site": ev["nearest"]["name"].replace("  ", " ") if ev["nearest"] else None,
                     "best_pct": ev["best"]["pct_hours"] if ev["best"] else None,
                     "other": ev["other_frp_share"], "bbox_adjust": S2c[eid].get("bbox_adjust")})

    def rank(r):
        return (not r["pass"], r["near_km"] if r["near_km"] is not None else 1e9,
                -(r["best_pct"] or 0), -int(r["start"].replace("-", "")))

    picks, used = {}, set()
    for role in ("PE-016", "PE-017"):
        for r in sorted((r for r in rows if r["role"] == role), key=rank):
            if r["pass"] and r["fire"] not in used:
                picks[role] = r["id"]
                used.add(r["fire"])
                break

    yn = {True: "pass", False: "FAIL", None: "n/a"}
    cols = ["firms", "near_40km", "hours_75", "other_20", "elevation", "tier_low", "no_overlap"]
    lines = ["# Replacement candidates for PE-016 and PE-017", "",
             "Screened 2026-10-10 under the final rules (`rules_final.py`) plus: tier Low, and no window overlap "
             f"with another final event within {OVERLAP_KM:.0f} km. Sources are on each row of `events_candidates.py`.",
             "", "| Candidate | Role | Window | " + " | ".join(cols) + " | Result | Tier (site, peak) | Nearest in-box site, km "
             "| Best % hours | Other-fire FRP | Notes |",
             "|" + "---|" * (len(cols) + 9)]
    for r in sorted(rows, key=lambda r: (r["role"], rank(r))):
        notes = "; ".join(x for x in [("clash: " + ", ".join(r["clash"])) if r["clash"] else "", r["bbox_adjust"] or "",
                                      "**PICK**" if picks.get(r["role"]) == r["id"] else ""] if x)
        tier = "—" if r["tier"] is None else f"{r['tier']} ({r['tier_site']}, {r['peak']})"
        other = "—" if r["other"] is None else f"{100 * r['other']:.1f}%"
        lines.append(f"| {r['id']} {r['name']} | {r['role']} | {r['start']} → {r['end']} | "
                     + " | ".join(yn[r["rules"][k]] for k in cols)
                     + f" | {'PASS' if r['pass'] else 'FAIL'} | {tier} | {r['near_site'] or '—'}, {r['near_km'] if r['near_km'] is not None else '—'} "
                     f"| {r['best_pct'] if r['best_pct'] is not None else '—'}% | {other} | {notes or '—'} |")
    lines += ["", "**Picks:** " + (", ".join(f"{role} → {cid}" for role, cid in picks.items()) or "none")]
    missing = [role for role in ("PE-016", "PE-017") if role not in picks]
    if missing:
        lines.append(f"**No passing candidate for:** {', '.join(missing)}")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    (CAND / "screen.json").write_text(json.dumps({"rows": rows, "picks": picks}, indent=1))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
