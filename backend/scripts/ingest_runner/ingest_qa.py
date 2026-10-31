"""QA of the ingested pilot events against docs/pilot_events.json and the data rules.

Run from backend/ (point POSTGRES_HOST/POSTGRES_PORT at the DB, e.g. localhost:5433):

    python scripts/ingest_runner/ingest_qa.py [--no-airnow] [--reports data/ingest_reports]
                                              [--out scripts/ingest_runner/reports/ingest_qa.md]

No table carries an event id, so each event's rows are selected by space and time:
AirNow and NCEI by the tight bbox over the event's UTC days, FIRMS by firms_bbox
over [firms_start_date, end_date]. No API calls; check (c) reads the raw AirNow
rows cached by scripts/pilot_verification (PILOT_VERIFY_CACHE, default its .cache/).

Checks per event:
  a  AirNow sites in the DB vs airnow_monitors_nearby (missing / extra)
  b  valid hours at the tier site and best site vs the verification note (~1 point)
  c  Red Bluff 061030007 (PE-001, PE-004, PE-013): stored valid_at = raw label + offset
     (raw values in [-5, 0) are stored as 0 by design; rows whose corrected hour falls
     outside the event window are not stored and not compared)
  d  pm25: no -999, none < 0, none < -5
  e  FIRMS rows inside firms_bbox x [firms_start_date, end_date]; SNPP rows > 0
  f  NCEI: >= 1 station in the tight bbox, best station >= 50% valid hours
  g  PurpleAir rows = 0
  h  AirNow rows shared by events with overlapping windows: (monitor, hour) rows inside
     both tight bboxes and both windows, per event pair (DATA-04 dedupes these and keeps
     the pair in the same fold)
  i  AirNow lead / tail coverage at the tier site: % of hours with a value in
     [start - lead, start) and after the last event hour up to end + tail
  j  monitor identity: every AirNow external_id is the hash of a normalized 9-character AQS code, and no
     AQS code maps to two monitors (codes are recovered from the raw AirNow cache)
Also listed: in-box AirNow sites whose AQS state code is not 06 (outside California).

--no-airnow runs only e, f and g (for a DB with FIRMS + NCEI but no AirNow yet).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
from app.core.config import settings  # noqa: E402
from ingestion.batch.batch_ingest import load_pilot_events  # noqa: E402
from ingestion.connectors.airnow import RAW_NEGATIVE_FLOOR, normalize_aqs_code  # noqa: E402
from ingestion.connectors.airnow_time_offsets import airnow_time_shift  # noqa: E402
from ingestion.normalize import stable_external_id  # noqa: E402

HOURS_TOL = 1.0          # (b) points of % hours
FIRMS_EDGE_EPS = 0.001   # (e) deg; FIRMS's own bbox filter keeps points within float rounding of an edge
NCEI_MIN_VALID = 50.0    # (f) % valid hours at the best station
RED_BLUFF = "061030007"
RED_BLUFF_EVENTS = ("PE-001", "PE-004", "PE-013")
CACHE = Path(os.environ.get("PILOT_VERIFY_CACHE") or BACKEND / "scripts/pilot_verification/.cache") / "airnow_cache"
ENV = "ST_MakeEnvelope(:w, :s, :e, :n, 4326)"


def window(start: str, end: str) -> tuple[datetime, datetime]:
    lo = datetime.combine(date.fromisoformat(start), datetime.min.time(), timezone.utc)
    hi = datetime.combine(date.fromisoformat(end) + timedelta(days=1), datetime.min.time(), timezone.utc)
    return lo, hi


def box(b: str, eps: float = 0.0) -> dict:
    w, s, e, n = (float(v) for v in b.split(","))
    return {"w": w - eps, "s": s - eps, "e": e + eps, "n": n + eps}


def aqs_code(aqs: str) -> str:
    return aqs.replace("-", "")


def monitor_ids_of(code: str) -> tuple[str, str]:
    """Monitor external_ids a 9-digit AQS code can be stored under.

    AirNow's FullAQSCode is not consistent: most sites come as 9 digits
    ("060650012"), some with the "840" country prefix ("840060072003").
    The connector hashes whichever string arrives.
    """
    return stable_external_id("airnow", code), stable_external_id("airnow", "840" + code)


def nm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def parse_note(note: str) -> dict:
    """Tier/best site AQS ids and best-site % hours from a verification_note."""
    out = {}
    m = re.search(r"tier site (.+?) \((\d\d-\d{3}-\d{4})\)", note)
    if m:
        out["tier_name"], out["tier_aqs"] = m.groups()
    m = re.search(r"best site (.+?) \((\d\d-\d{3}-\d{4})\) ([\d.]+)% of hours", note)
    if m:
        out["best_name"], out["best_aqs"], out["best_pct"] = m.group(1), m.group(2), float(m.group(3))
    return out


def expected_pct(eid: str, aqs: str) -> float | None:
    """% hours for any in-box site from the local final run, when it is there."""
    p = BACKEND / "scripts/pilot_verification/out_final/stage2.json"
    if not p.exists():
        return None
    s2 = json.loads(p.read_text()).get(eid, {})
    return next((s["pct_hours"] for s in s2.get("sites", []) if s["aqs"] == aqs), None)


def red_bluff_raw(lo: datetime, hi: datetime) -> dict[datetime, float]:
    """Raw Red Bluff rows (UTC label -> RawConcentration) from the cached AirNow pulls."""
    raw = {}
    if not CACHE.exists():
        return raw
    for f in CACHE.glob("*.json"):
        for r in json.loads(f.read_text()):
            if str(r.get("FullAQSCode"))[-9:] != RED_BLUFF:
                continue
            t = datetime.fromisoformat(r["UTC"]).replace(tzinfo=timezone.utc)
            v = float(r["RawConcentration"])
            if lo <= t < hi and v != -999:
                raw[t] = v
    return raw


def load_coverage(reports: Path, eid: str) -> dict | None:
    """Per source, the coverage entry from the pass that actually ran it.

    Ingest can run in passes (e.g. FIRMS + NCEI first, AirNow later with
    --resume); each pass writes <reports>/<pass>/<event>.json or
    <reports>/<event>.json. Entries that were skipped (--skip-source) or
    resumed are ignored when a pass that ran the source exists.
    """
    merged = {}
    for p in sorted(reports.glob(f"**/{eid}.json")):
        for source, cov in json.loads(p.read_text())[0]["sources"].items():
            ran = not cov.get("skipped_resume") and "skipped by --skip-source" not in cov.get("gaps", [])
            if ran or source not in merged:
                merged[source] = dict(cov, ran=ran)
    return merged or None


def shared_airnow(c, events) -> list[dict]:
    """(h) For every pair of events with overlapping windows, AirNow rows inside both."""
    out = []
    for i, a in enumerate(events):
        for b in events[i + 1:]:
            a_lo, a_hi = window(a.start_date, a.end_date)
            b_lo, b_hi = window(b.start_date, b.end_date)
            lo, hi = max(a_lo, b_lo), min(a_hi, b_hi)
            if lo >= hi:
                continue
            ba, bb = box(a.bbox), box(b.bbox)
            n, sites = c.execute(text("""
                select count(*), count(distinct o.monitor_id)
                from observations o join monitors m on m.id = o.monitor_id
                where o.correction = 'regulatory' and o.valid_at >= :lo and o.valid_at < :hi
                  and ST_Intersects(m.geom::geometry, ST_MakeEnvelope(:aw, :as_, :ae, :an, 4326))
                  and ST_Intersects(m.geom::geometry, ST_MakeEnvelope(:bw, :bs, :be, :bn, 4326))"""),
                dict(lo=lo, hi=hi, aw=ba["w"], as_=ba["s"], ae=ba["e"], an=ba["n"],
                     bw=bb["w"], bs=bb["s"], be=bb["e"], bn=bb["n"])).one()
            out.append({"a": a.event_id, "b": b.event_id, "overlap": f"{lo.date()} → {(hi - timedelta(days=1)).date()}",
                        "rows": n, "sites": sites})
    return out


def monitor_identity(c, events) -> dict:
    """(j) Map AirNow monitors back to AQS codes; list in-box sites outside California."""
    raw_codes = set()
    if CACHE.exists():
        for f in CACHE.glob("*.json"):
            for r in json.loads(f.read_text()):
                if r.get("FullAQSCode"):
                    raw_codes.add(str(r["FullAQSCode"]).strip())
    canon = {x: normalize_aqs_code(x) for x in raw_codes}
    by_hash9 = {stable_external_id("airnow", c9): c9 for c9 in set(canon.values())}
    by_hash_long = {stable_external_id("airnow", x): x for x, c9 in canon.items() if c9 != x}
    mons = c.execute(text("""select external_id, name, ST_X(geom::geometry) lon, ST_Y(geom::geometry) lat
                             from monitors where source = 'airnow'""")).mappings().all()
    out = {"monitors": len(mons), "nine_digit": 0, "prefixed": [], "unmapped": [], "split_codes": [],
           "out_of_state": []}
    codes = {}
    for m in mons:
        if m["external_id"] in by_hash9:
            out["nine_digit"] += 1
            codes.setdefault(by_hash9[m["external_id"]], []).append(m["name"])
        elif m["external_id"] in by_hash_long:
            out["prefixed"].append(f"{nm(m['name'])} ({by_hash_long[m['external_id']]})")
        else:
            out["unmapped"].append(nm(m["name"]))
    out["split_codes"] = [f"{c9}: {', '.join(n)}" for c9, n in codes.items() if len(n) > 1]
    code_of = {k: v for k, v in by_hash9.items()}
    for ev in events:
        b = box(ev.bbox)
        for m in mons:
            c9 = code_of.get(m["external_id"])
            if c9 and c9[:2] != "06" and b["w"] <= m["lon"] <= b["e"] and b["s"] <= m["lat"] <= b["n"]:
                out["out_of_state"].append({"event": ev.event_id, "name": nm(m["name"]),
                                            "aqs": f"{c9[:2]}-{c9[2:5]}-{c9[5:]}", "state_code": c9[:2]})
    return out


def qa_event(c, ev, cov, airnow=True) -> dict:
    lo, hi = window(ev.start_date, ev.end_date)
    tight, wide = box(ev.bbox), box(ev.firms_bbox, FIRMS_EDGE_EPS)
    flo, _ = window(ev.firms_start_date, ev.end_date)
    total_h = (hi - lo).total_seconds() / 3600
    note = parse_note(ev.verification_note)
    res = {"event_id": ev.event_id, "flags": []}
    flag = res["flags"].append

    res["e"] = res["f"] = None
    if not airnow:
        rows = []
        return qa_firms_ncei(c, ev, cov, res, lo, hi, tight, wide, flo, total_h)
    # ---- (a) AirNow sites
    rows = c.execute(text(f"""
        select m.external_id, m.name, count(distinct o.valid_at) as hours, count(*) as n
        from observations o join monitors m on m.id = o.monitor_id
        where m.source = 'airnow' and o.correction = 'regulatory'
          and o.valid_at >= :lo and o.valid_at < :hi and o.pm25 is not null
          and ST_Intersects(m.geom::geometry, {ENV})
        group by m.external_id, m.name"""), dict(lo=lo, hi=hi, **tight)).mappings().all()
    db_names = {nm(r["name"]) for r in rows}
    cfg_names = {nm(n) for n in ev.airnow_monitors_nearby}
    res["airnow_sites"] = len(rows)
    res["airnow_rows"] = sum(r["n"] for r in rows)
    res["a_missing"] = sorted(cfg_names - db_names)
    res["a_extra"] = sorted(db_names - cfg_names)
    if res["a_missing"]:
        flag(f"a: config site(s) with no rows in the DB: {', '.join(res['a_missing'])}")
    if res["a_extra"]:
        flag(f"a: DB site(s) not in airnow_monitors_nearby: {', '.join(res['a_extra'])}")

    # ---- (b) valid hours at the tier and best sites
    hours = {r["external_id"]: r["hours"] for r in rows}
    res["b"] = {}
    for role in ("tier", "best"):
        aqs = note.get(f"{role}_aqs")
        if not aqs:
            continue
        got = round(100 * max(hours.get(m, 0) for m in monitor_ids_of(aqs_code(aqs))) / total_h, 1)
        exp = note["best_pct"] if role == "best" else expected_pct(ev.event_id, aqs)
        res["b"][role] = {"aqs": aqs, "db_pct": got, "expected_pct": exp}
        if exp is not None and abs(got - exp) > HOURS_TOL:
            flag(f"b: {role} site {aqs} has {got}% valid hours in the DB vs {exp}% at verification")

    # ---- (c) Red Bluff offset
    if ev.event_id in RED_BLUFF_EVENTS:
        stored = dict(c.execute(text("""
            select o.valid_at, o.pm25 from observations o join monitors m on m.id = o.monitor_id
            where m.external_id in (:m9, :m12) and o.valid_at >= :lo and o.valid_at < :hi"""),
            dict(zip(("m9", "m12"), monitor_ids_of(RED_BLUFF)),
                 lo=lo - timedelta(hours=2), hi=hi + timedelta(hours=2))).all())
        raw = red_bluff_raw(lo, hi)
        shifted = same = 0
        samples = []
        raw = {t: max(v, 0.0) for t, v in raw.items()
               if v >= RAW_NEGATIVE_FLOOR and lo <= t + airnow_time_shift(RED_BLUFF, t) < hi}
        for t, v in sorted(raw.items()):
            corrected = t + airnow_time_shift(RED_BLUFF, t)
            if corrected in stored and abs(stored[corrected] - v) < 1e-6:
                shifted += 1
                if len(samples) < 2:
                    samples.append({"raw_label_utc": t.isoformat(), "stored_valid_at": corrected.isoformat(),
                                    "pm25": v, "shift_h": (corrected - t).total_seconds() / 3600})
            elif t in stored and abs(stored[t] - v) < 1e-6:
                same += 1
        res["c"] = {"raw_rows": len(raw), "stored_rows": len(stored), "match_corrected": shifted,
                    "match_unshifted_only": same, "samples": samples}
        if not raw:
            flag("c: no cached raw Red Bluff rows to compare against (PILOT_VERIFY_CACHE)")
        elif shifted < 0.95 * len(raw):
            flag(f"c: only {shifted}/{len(raw)} raw Red Bluff rows stored at the corrected hour")

    # ---- (d) pm25 values, over the whole AirNow window (event + lead + tail)
    alo, ahi = window(ev.airnow_start_date, ev.airnow_end_date)
    bad = c.execute(text(f"""
        select count(*) filter (where o.pm25 = -999), count(*) filter (where o.pm25 < 0),
               count(*) filter (where o.pm25 < -5), count(*) filter (where o.pm25 is null)
        from observations o join monitors m on m.id = o.monitor_id
        where o.valid_at >= :lo and o.valid_at < :hi and ST_Intersects(m.geom::geometry, {ENV})"""),
        dict(lo=alo, hi=ahi, **tight)).one()
    res["d"] = dict(zip(("minus999", "below0", "below_minus5", "null"), bad))
    if bad[0] or bad[1]:
        flag(f"d: pm25 -999 rows {bad[0]}, rows < 0 {bad[1]} (< -5: {bad[2]})")

    # ---- (i) AirNow lead / tail coverage at the tier site
    res["i"] = None
    if note.get("tier_aqs"):
        def cover(t0, t1):
            n = c.execute(text("""
                select count(distinct o.valid_at) from observations o join monitors m on m.id = o.monitor_id
                where m.external_id in (:m9, :m12) and o.valid_at >= :lo and o.valid_at < :hi
                  and o.pm25 is not null"""),
                dict(zip(("m9", "m12"), monitor_ids_of(aqs_code(note["tier_aqs"]))), lo=t0, hi=t1)).scalar()
            return round(100 * n / ((t1 - t0).total_seconds() / 3600), 1)
        res["i"] = {"aqs": note["tier_aqs"], "lead_pct": cover(alo, lo), "tail_pct": cover(hi, ahi)}
        if res["i"]["lead_pct"] == 0 or res["i"]["tail_pct"] == 0:
            flag(f"i: tier site {note['tier_aqs']} has no AirNow values in the "
                 f"{'lead' if res['i']['lead_pct'] == 0 else 'tail'} window")

    return qa_firms_ncei(c, ev, cov, res, lo, hi, tight, wide, flo, total_h)


def qa_firms_ncei(c, ev, cov, res, lo, hi, tight, wide, flo, total_h) -> dict:
    flag = res["flags"].append
    # ---- (e) FIRMS
    sat = dict(c.execute(text(f"""
        select satellite, count(*) from fire_detections
        where detected_at >= :lo and detected_at < :hi and ST_Intersects(geom::geometry, {ENV})
        group by satellite"""), dict(lo=flo, hi=hi, **wide)).all())
    span = c.execute(text(f"""
        select min(detected_at)::date, max(detected_at)::date,
               count(*) filter (where detected_at < :start),
               count(*) filter (where not ST_Intersects(geom::geometry,
                   ST_MakeEnvelope(:tw, :ts, :te, :tn, 4326)))
        from fire_detections
        where detected_at >= :lo and detected_at < :hi and ST_Intersects(geom::geometry, {ENV})"""),
        dict(lo=flo, hi=hi, start=lo, tw=tight["w"], ts=tight["s"], te=tight["e"], tn=tight["n"], **wide)).one()
    fetched = (cov or {}).get("firms", {}).get("rows_fetched")
    res["e"] = {"by_satellite": sat, "rows": sum(sat.values()), "first": str(span[0]), "last": str(span[1]),
                "lead_rows": span[2], "margin_rows": span[3], "fetched": fetched}
    if not sat.get("VIIRS_SNPP"):
        flag("e: no VIIRS_SNPP rows")
    if fetched is not None and sum(sat.values()) < fetched:
        flag(f"e: {sum(sat.values())} rows in firms_bbox x window < {fetched} fetched")

    # ---- (f) NCEI: stations in ncei_bbox (bbox + 50 km) over [ncei_start_date, end_date];
    # valid hours are counted over the event window only
    nlo, _ = window(ev.ncei_start_date, ev.end_date)
    st = c.execute(text(f"""
        select station_id,
               count(distinct date_trunc('hour', valid_at)) filter (
                   where valid_at >= :lo and wind_speed_ms is not null and temp_c is not null
                     and rh_pct is not null) as valid_h,
               count(*) as n
        from weather_observations
        where valid_at >= :nlo and valid_at < :hi and ST_Intersects(geom::geometry, {ENV})
        group by station_id order by valid_h desc"""), dict(lo=lo, nlo=nlo, hi=hi, **box(ev.ncei_bbox))).mappings().all()
    best = st[0] if st else None
    best_pct = round(100 * best["valid_h"] / total_h, 1) if best else 0.0
    res["f"] = {"stations": len(st), "rows": sum(r["n"] for r in st),
                "best_station": best["station_id"] if best else None, "best_valid_pct": best_pct}
    if not st:
        flag("f: no NCEI station in the bbox + 50 km")
    elif best_pct < NCEI_MIN_VALID:
        flag(f"f: best NCEI station {best['station_id']} has {best_pct}% valid hours (< {NCEI_MIN_VALID:.0f}%)")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports", default=str(BACKEND / "data/ingest_reports"), help="batch_ingest coverage reports")
    ap.add_argument("--out", default=str(BACKEND / "scripts/ingest_runner/reports/ingest_qa.md"))
    ap.add_argument("--no-airnow", action="store_true", help="run only checks e, f and g")
    args = ap.parse_args()

    events = load_pilot_events(BACKEND / "docs/pilot_events.json")
    eng = create_engine(settings.database_url)
    results = []
    with eng.connect() as c:
        for ev in events:
            cov = load_coverage(Path(args.reports), ev.event_id)
            r = qa_event(c, ev, cov, airnow=not args.no_airnow)
            r["coverage"] = cov
            results.append(r)
        pa = c.execute(text("""select (select count(*) from observations where correction like 'purpleair%'),
                                      (select count(*) from monitors where source = 'purpleair')""")).one()
        windows = " or ".join(
            f"(detected_at >= '{window(e.firms_start_date, e.end_date)[0].isoformat()}' and "
            f"detected_at < '{window(e.firms_start_date, e.end_date)[1].isoformat()}' and "
            "ST_Intersects(geom::geometry, ST_MakeEnvelope({w}, {s}, {e}, {n}, 4326)))".format(**box(e.firms_bbox, FIRMS_EDGE_EPS))
            for e in events)
        stray = c.execute(text(f"select count(*) from fire_detections where not ({windows})")).scalar()
        shared = [] if args.no_airnow else shared_airnow(c, events)
        ident = None if args.no_airnow else monitor_identity(c, events)

    runs = BACKEND / "data/ingest_runs"
    summaries = [json.loads(f.read_text()) for f in sorted(runs.glob("summary_*.json"))]
    logs = "".join(f.read_text() for f in sorted(runs.glob("ingest_*.log")))
    na = "n/a (no AirNow)" if args.no_airnow else None

    lines = ["# Ingest QA", "",
             f"{len(events)} events from `backend/docs/pilot_events.json`, checked by "
             "`backend/scripts/ingest_runner/ingest_qa.py`"
             + (" with `--no-airnow` (checks e, f, g only)" if args.no_airnow else "")
             + ". Rows are selected by space and time (no table carries an event id).", "",
             "## Ingest", "",
             "| Event | FIRMS rows by satellite (SNPP / NOAA-20 / MODIS T+A) | FIRMS requests (retries) "
             "| AirNow rows, sites | NCEI rows, stations | null_counts | gaps | seconds |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        eid, e = r["event_id"], r["e"]["by_satellite"]
        modis = e.get("MODIS_Terra", 0) + e.get("MODIS_Aqua", 0)
        req = sum(sm.get(eid, {}).get("requests", {}).get("firms.modaps.eosdis.nasa.gov", 0) for sm in summaries)
        secs = sum(sm.get(eid, {}).get("seconds", 0) for sm in summaries)
        retries = len(re.findall(rf"\[firms:{eid}:[^\]]*\] attempt \d+/\d+ failed", logs))
        cov = r["coverage"] or {}
        nulls = "; ".join(f"{s}: " + ", ".join(f"{k} {v}" for k, v in (cov.get(s) or {}).get("null_counts", {}).items() if v)
                          for s in ("firms", "airnow", "ncei") if any((cov.get(s) or {}).get("null_counts", {}).values()))
        gaps = "; ".join(f"{s}: {g}" for s in ("firms", "airnow", "ncei", "purpleair")
                         for g in (cov.get(s) or {}).get("gaps", []))
        an = na or f"{r['airnow_rows']:,}, {r['airnow_sites']}"
        lines.append(f"| {eid} | {r['e']['rows']:,} ({e.get('VIIRS_SNPP', 0):,} / {e.get('VIIRS_NOAA20', 0):,} / {modis:,}) "
                     f"| {req} ({retries}) | {an} | {r['f']['rows']:,}, {r['f']['stations']} | {nulls or '—'} "
                     f"| {gaps or '—'} | {secs} |")

    lines += ["", "## Checks", "",
              "| Event | (a) AirNow sites missing / extra | (b) tier site % h DB / verif. | (b) best site % h DB / verif. "
              "| (c) Red Bluff offset | (d) pm25 -999 / <0 / <-5 | (e) FIRMS dates, lead rows, margin rows "
              "| (f) NCEI stations (bbox + 50 km), best % valid | (i) tier site lead / tail % | Flags |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        b = r.get("b") or {}

        def pct(k):
            if na or k not in b:
                return na or "—"
            exp = b[k]["expected_pct"]
            return f"{b[k]['db_pct']} / {exp if exp is not None else '—'} ({b[k]['aqs']})"

        c_ = r.get("c")
        cc = na or (f"{c_['match_corrected']}/{c_['raw_rows']} at corrected hour" if c_ else "n/a")
        aa = na or f"{len(r['a_missing'])} / {len(r['a_extra'])}"
        dd = na or f"{r['d']['minus999']} / {r['d']['below0']} / {r['d']['below_minus5']}"
        i_ = r.get("i")
        ii = na or (f"{i_['lead_pct']} / {i_['tail_pct']}" if i_ else "—")
        lines.append(f"| {r['event_id']} | {aa} | {pct('tier')} | {pct('best')} | {cc} | {dd} "
                     f"| {r['e']['first']} → {r['e']['last']}, {r['e']['lead_rows']:,}, {r['e']['margin_rows']:,} "
                     f"| {r['f']['stations']}, {r['f']['best_valid_pct']}% ({r['f']['best_station'] or '—'}) "
                     f"| {ii} "
                     f"| {len(r['flags']) or '—'} |")
    lines += ["", f"**(g) PurpleAir:** {pa[0]} observation rows, {pa[1]} monitors (expected 0)."
              + ("" if pa == (0, 0) else " **FLAG**"),
              f"**(e) FIRMS rows outside every event's firms_bbox × window:** {stray} (expected 0)."
              + ("" if stray == 0 else " **FLAG**"), "", "## Flags", ""]
    flags = [f"- **{r['event_id']}** {f}" for r in results for f in r["flags"]]
    if pa != (0, 0):
        flags.append(f"- g: {pa[0]} PurpleAir observation rows, {pa[1]} PurpleAir monitors")
    if stray:
        flags.append(f"- e: {stray} FIRMS rows outside every event's firms_bbox × window")
    if ident:
        if ident["prefixed"]:
            flags.append(f"- j: monitor id(s) built from a prefixed code: {', '.join(ident['prefixed'])}")
        if ident["split_codes"]:
            flags.append(f"- j: AQS code(s) on more than one monitor: {'; '.join(ident['split_codes'])}")
    lines += flags or ["None."]
    if not args.no_airnow:
        lines += ["", "## (h) AirNow rows shared by events with overlapping windows", "",
                  "(monitor, hour) rows inside both events' tight bboxes and both windows. DATA-04 dedupes these "
                  "and keeps each pair in the same fold.", "",
                  "| Pair | Window overlap | Shared rows | Shared sites |", "|---|---|---|---|"]
        lines += [f"| {x['a']} × {x['b']} | {x['overlap']} | {x['rows']:,} | {x['sites']} |" for x in shared] or ["| — | — | 0 | 0 |"]
        lines += ["", "## (j) Monitor identity", "",
                  f"{ident['monitors']} AirNow monitors: {ident['nine_digit']} built from a 9-digit code, "
                  f"{len(ident['prefixed'])} from a prefixed code, {len(ident['unmapped'])} not found in the raw "
                  f"AirNow cache{(' (' + ', '.join(ident['unmapped']) + ')') if ident['unmapped'] else ''}; "
                  f"{len(ident['split_codes'])} AQS code(s) on more than one monitor.", "",
                  "## In-box AirNow sites outside California (AQS state code not 06)", "",
                  "| Event | Site | AQS id | State code |", "|---|---|---|---|"]
        lines += [f"| {o['event']} | {o['name']} | {o['aqs']} | {o['state_code']} |" for o in ident["out_of_state"]] \
            or ["| — | — | — | — |"]
        lines += ["", "## (c) Red Bluff (061030007) samples", ""]
        for r in results:
            if r.get("c"):
                lines.append(f"- **{r['event_id']}**: {r['c']['match_corrected']} of {r['c']['raw_rows']} raw rows "
                             f"stored at label + offset, {r['c']['match_unshifted_only']} only at the raw label.")
                for smp in r["c"]["samples"]:
                    lines.append(f"  - raw label {smp['raw_label_utc']} → stored {smp['stored_valid_at']} "
                                 f"(shift {smp['shift_h']:+.0f} h), pm25 {smp['pm25']}")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
