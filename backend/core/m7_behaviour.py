"""backend/core/m7_behaviour.py — ARCHITECTURE.md §5 M7 (rule features only;
Isolation Forest is explicitly "only if hours remain" and is out of scope
for this build).

Five rule features, each normalised 0-1, combined per config/weights.yaml's
`behaviour: {method: max_of_rules}` — any single strong anomaly should carry
the signal rather than being averaged away by four unremarkable ones.
"""

from __future__ import annotations

from datetime import datetime

from backend.core.geometry import km_per_deg
from backend.core.m5_ais_recon import haversine_km


def _heading_delta(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def unexpected_stop(fixes: list[dict]) -> float:
    if len(fixes) < 3:
        return 0.0
    interior = fixes[1:-1]
    min_sog = min(f["sog"] for f in interior)
    return max(0.0, min(1.0, 1 - min_sog / 2.0))


def sharp_turn(fixes: list[dict]) -> float:
    if len(fixes) < 2:
        return 0.0
    max_delta = max(
        _heading_delta(f1["heading"], f2["heading"]) for f1, f2 in zip(fixes, fixes[1:])
    )
    return max(0.0, min(1.0, (max_delta - 30.0) / 60.0))


def slowdown(fixes: list[dict]) -> float:
    if len(fixes) < 2:
        return 0.0
    speeds = [f["sog"] for f in fixes]
    median = sorted(speeds)[len(speeds) // 2]
    if median <= 0:
        return 0.0
    return max(0.0, min(1.0, (median - min(speeds)) / median))


def loitering(fixes: list[dict]) -> float:
    if len(fixes) < 2:
        return 0.0
    lat0 = fixes[0]["lat"]
    km_lon, km_lat = km_per_deg(lat0)
    path_km = sum(
        haversine_km(f1["lon"], f1["lat"], f2["lon"], f2["lat"])
        for f1, f2 in zip(fixes, fixes[1:])
    )
    net_km = haversine_km(fixes[0]["lon"], fixes[0]["lat"], fixes[-1]["lon"], fixes[-1]["lat"])
    if path_km < 1e-6:
        return 0.0
    return max(0.0, min(1.0, 1 - net_km / path_km))


def ais_gap_in_window(fixes: list[dict], window_start: datetime, window_end: datetime) -> float:
    if len(fixes) < 2:
        return 1.0  # a track with no fixes at all in range is maximally suspicious of a gap
    times = sorted(datetime.fromisoformat(f["ts"]) for f in fixes)
    intervals = [(t2 - t1).total_seconds() for t1, t2 in zip(times, times[1:])]
    median_interval = sorted(intervals)[len(intervals) // 2] if intervals else 1.0
    max_gap_in_window = 0.0
    for t1, t2, gap in zip(times, times[1:], intervals):
        overlaps = t2 >= window_start and t1 <= window_end
        if overlaps:
            max_gap_in_window = max(max_gap_in_window, gap)
    if median_interval <= 0:
        return 0.0
    ratio = max_gap_in_window / median_interval
    return max(0.0, min(1.0, (ratio - 2.0) / 4.0))


def behaviour_score(fixes: list[dict], window_start: datetime, window_end: datetime) -> dict:
    rules = {
        "unexpected_stop": unexpected_stop(fixes),
        "sharp_turn": sharp_turn(fixes),
        "slowdown": slowdown(fixes),
        "loitering": loitering(fixes),
        "ais_gap_in_window": ais_gap_in_window(fixes, window_start, window_end),
    }
    dominant = max(rules, key=rules.get)
    return {"B": round(max(rules.values()), 4), "rules": {k: round(v, 4) for k, v in rules.items()}, "dominant_rule": dominant}
