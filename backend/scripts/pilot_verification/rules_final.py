"""Final pilot-event rules, evaluated on stage2 + item3 + item6 output.

An event passes when every rule holds:
  firms      >= 1 FIRMS detection in the event's own cluster
  near_40km  nearest in-box AirNow site <= 40 km from the fire detections
  hours_75   best site (most hours) has >= 75% of the window's hours
  other_20   in-box FRP from other fires < 20%
  elevation  tier site peak >= 2x baseline and peak - baseline >= 10 (non-Low tiers only)

Tier = item3's TIER_RANGES on the max peak daily mean over in-box sites
(days with >= 18 h); the site holding that peak is the tier site.
"""
NEAR_KM = 40.0
MIN_PCT_HOURS = 75.0
MAX_OTHER_FRP = 0.20
ELEV_RATIO = 2.0
ELEV_DIFF = 10.0


def evaluate(r, i3, i6):
    """Rule results for one event: stage2 record r, item3 record i3, item6 record i6."""
    sites = [s for s in r["sites"] if s["pct_hours"] > 0]
    near = min((s for s in sites if s["dist_fire_km"] is not None), key=lambda s: s["dist_fire_km"], default=None)
    best = max(sites, key=lambda s: s["pct_hours"], default=None)
    fire = r.get("fire_detections") or 0
    other = r.get("other_frp_share")
    tier = (i3 or {}).get("max_tier")
    elev = (i6 or {}).get("max") or {}

    rules = {
        "firms": fire >= 1,
        "near_40km": near is not None and near["dist_fire_km"] <= NEAR_KM,
        "hours_75": best is not None and best["pct_hours"] >= MIN_PCT_HOURS,
        "other_20": other is not None and other < MAX_OTHER_FRP,
    }
    if tier is None:
        rules["elevation"] = False
    elif tier == "low":
        rules["elevation"] = None  # not applied to Low
    else:
        base, peak = elev.get("baseline"), elev.get("peak")
        rules["elevation"] = (base is not None and peak is not None
                              and peak >= ELEV_RATIO * base and peak - base >= ELEV_DIFF)
    return {
        "rules": rules,
        "pass": all(v is not False for v in rules.values()),
        "tier": tier,
        "tier_site": (i3 or {}).get("max_site"),
        "tier_site_name": (i3 or {}).get("max_name"),
        "peak": (i3 or {}).get("max_peak"),
        "peak_day": (i3 or {}).get("max_day"),
        "baseline": elev.get("baseline"),
        "baseline_source": elev.get("baseline_source"),
        "peak_minus_baseline": elev.get("peak_minus_baseline"),
        "peak_over_baseline": elev.get("peak_over_baseline"),
        "fire_detections": fire,
        "nearest": near,
        "best": best,
        "other_frp_share": other,
    }
