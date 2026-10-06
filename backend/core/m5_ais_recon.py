"""backend/core/m5_ais_recon.py — ARCHITECTURE.md §5 M5.

Pipeline: spatial filter (origin region + buffer) -> temporal filter (window
+/- margin) -> reachability check (could this vessel physically be at the
origin region in-window at plausible speed?) -> track rebuild -> quality
scoring.

`Q` uses the exact formula in §5 M5:

    Q = clamp(1 - 0.5*gap_fraction - 0.3*jump_rate - 0.2*implausible_rate, 0.2, 1.0)

Enforced here, not just documented: Q is a pure function of (gap_fraction,
jump_rate, implausible_rate) and is monotonically non-increasing in each —
missing AIS can only ever lower confidence, never raise it (§5's explicit
requirement). See tests/test_m5.py for the enforcing test.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from backend.core.geometry import km_per_deg

KNOT_TO_KMH = 1.852


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    km_lon, km_lat = km_per_deg((lat1 + lat2) / 2)
    dx = (lon2 - lon1) * km_lon
    dy = (lat2 - lat1) * km_lat
    return math.hypot(dx, dy)


def compute_quality(gap_fraction: float, jump_rate: float, implausible_rate: float) -> float:
    q = 1 - 0.5 * gap_fraction - 0.3 * jump_rate - 0.2 * implausible_rate
    return max(0.2, min(1.0, q))


def track_quality(fixes: list[dict], max_speed_kn: float) -> dict:
    n = len(fixes)
    if n < 2:
        return {"gap_fraction": 1.0, "mean_interval_s": 0.0, "jump_count": 0, "implausible_speed_count": 0, "score": 0.2}

    times = [datetime.fromisoformat(f["ts"]) for f in fixes]
    intervals_s = [(t2 - t1).total_seconds() for t1, t2 in zip(times, times[1:])]
    intervals_s = [i for i in intervals_s if i > 0]
    median_interval = sorted(intervals_s)[len(intervals_s) // 2] if intervals_s else 1.0
    span_s = (times[-1] - times[0]).total_seconds()
    expected_count = span_s / median_interval + 1 if median_interval > 0 else n
    gap_fraction = max(0.0, min(1.0, 1 - n / expected_count)) if expected_count > 0 else 0.0

    jump_count = 0
    implausible_count = 0
    for (lon1, lat1, t1), (lon2, lat2, t2) in zip(
        [(f["lon"], f["lat"], t) for f, t in zip(fixes, times)],
        [(f["lon"], f["lat"], t) for f, t in zip(fixes[1:], times[1:])],
    ):
        dt_h = (t2 - t1).total_seconds() / 3600.0
        if dt_h <= 0:
            continue
        dist_km = haversine_km(lon1, lat1, lon2, lat2)
        implied_speed_kn = (dist_km / KNOT_TO_KMH) / dt_h
        if implied_speed_kn > max_speed_kn:
            implausible_count += 1
        if implied_speed_kn > 3 * max_speed_kn:
            jump_count += 1

    n_pairs = max(1, n - 1)
    jump_rate = jump_count / n_pairs
    implausible_rate = implausible_count / n_pairs
    score = compute_quality(gap_fraction, jump_rate, implausible_rate)

    return {
        "gap_fraction": round(gap_fraction, 4),
        "mean_interval_s": round(sum(intervals_s) / len(intervals_s), 1) if intervals_s else 0.0,
        "jump_count": jump_count,
        "implausible_speed_count": implausible_count,
        "score": round(score, 4),
    }


def _is_reachable(
    fixes: list[dict],
    origin_lon: float,
    origin_lat: float,
    window_start: datetime,
    window_end: datetime,
    buffer_km: float,
    max_speed_kn: float,
) -> bool:
    max_speed_kmh = max_speed_kn * KNOT_TO_KMH
    for f in fixes:
        t = datetime.fromisoformat(f["ts"])
        dist_km = haversine_km(f["lon"], f["lat"], origin_lon, origin_lat)
        if window_start <= t <= window_end:
            if dist_km <= buffer_km:
                return True
            continue
        bound = window_start if t < window_start else window_end
        dt_h = abs((t - bound).total_seconds()) / 3600.0
        if dt_h <= 1e-6:
            continue
        required_kmh = max(0.0, dist_km - buffer_km) / dt_h
        if required_kmh <= max_speed_kmh:
            return True
    return False


def reconstruct(
    raw_tracks: list[dict],
    origin: dict,
    buffer_km: float = 25.0,
    max_speed_kn: float = 25.0,
    min_fixes: int = 5,
    temporal_margin_h: float = 24.0,
) -> list[dict]:
    """Filter the raw AIS feed down to physically-plausible candidates and
    attach a quality score to each. `origin` is the OriginEstimate dict (for
    its high_prob_geometry centroid and window)."""
    from shapely.geometry import shape

    high_poly = shape(origin["high_prob_geometry"])
    origin_lon, origin_lat = high_poly.centroid.x, high_poly.centroid.y
    window_start = datetime.fromisoformat(origin["window_start"]) - timedelta(hours=temporal_margin_h)
    window_end = datetime.fromisoformat(origin["window_end"]) + timedelta(hours=temporal_margin_h)

    kept = []
    for track in raw_tracks:
        fixes = track["fixes"]
        if len(fixes) < min_fixes:
            continue
        if not _is_reachable(fixes, origin_lon, origin_lat, window_start, window_end, buffer_km, max_speed_kn):
            continue
        quality = track_quality(fixes, max_speed_kn)
        kept.append({
            "track_id": track["track_id"],
            "mmsi": track.get("mmsi"),
            "vessel_type": track.get("vessel_type"),
            "fixes": fixes,
            "quality": quality,
            "source": track.get("source", "synthetic"),
        })
    return kept
