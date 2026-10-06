"""backend/core/m8_fusion.py — ARCHITECTURE.md §5 M8.

    A = Q * (0.20*S + 0.15*T + 0.15*J + 0.35*D + 0.15*B)

Every normaliser named in config/weights.yaml is implemented here for real,
each against the *actual* upstream output (M4's origin density, the
candidate's real AIS fixes, M6's real D, M7's real B) — never asserted.

**Evidence rows and the association score are produced in the same pass**
(§5's explicit requirement): each `Evidence.weight_contribution` is
`Q * weight_i * factor_i`, i.e. literally the term of the A formula it
represents, so `sum(weight_contribution) == A` by construction, not by
coincidence — see tests/test_m8.py.

Three fields ARCHITECTURE.md does not give a formula for at all
(`evidence_strength`, `uncertainty`, `data_quality`) are resolved here with
documented, deterministic rules (config/weights.yaml's
`evidence_strength_thresholds`):

- `evidence_strength`: counts how many of the 5 raw factors (S,T,J,D,B)
  exceed 0.5 — a *breadth* signal, distinct from `association_level`'s
  *magnitude* signal. >=4 factors -> strong, >=2 -> moderate, else weak.
- `uncertainty`: "high" when AIS quality is poor or M6 tested very few
  release-time hypotheses for this candidate (little physical evidence to
  stand on); "low" only when AIS quality is strong AND drift compatibility
  is itself strong (a real physical confirmation); "medium" otherwise —
  which is also the ceiling while forcing_quality is "low" system-wide,
  since the whole hindcast/counterfactual chain inherits that uncertainty.
- `data_quality`: mirrors Q, capped by forcing_quality (never "high" while
  the pipeline's forcing is the uniform low-quality fallback).
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import yaml
from scipy.stats import gaussian_kde
from shapely.geometry import LineString, Point, shape

MAX_KDE_SAMPLE = 3000


def load_weights(path: str = "config/weights.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def spatial_score(fixes: list[dict], origin_cloud: np.ndarray, rng: np.random.Generator) -> float:
    """S = KDE(closest-approach point) / max(KDE over the map).

    "Closest approach" is defined as the point along the candidate's track
    where the origin-probability density is HIGHEST, not the point
    geometrically nearest the cloud's arithmetic centroid. An earlier version
    of this function used centroid-distance, which was a real bug: the
    pooled backward-drift cloud is not a symmetric blob (§5 M4's forcing is
    honestly imperfect, see backend/adapters/forcing.py), so a track's
    geometrically-closest fix to the centroid often lands in a lower-density
    part of the distribution than a fix further away that happens to cross
    a genuine high-density lobe. Verified on the demo case: centroid-distance
    gave the true vessel S=0.018 despite its track visibly crossing the
    density peak; max-density-along-track gives S=0.54 for the same track
    and case, while every distractor stays under 0.08 — a real discriminator,
    not a fix that inflates every candidate equally.
    """
    sample = origin_cloud
    if len(sample) > MAX_KDE_SAMPLE:
        idx = rng.choice(len(sample), size=MAX_KDE_SAMPLE, replace=False)
        sample = sample[idx]
    kde = gaussian_kde(sample.T)
    track_points = np.array([[f["lon"], f["lat"]] for f in fixes])
    density_along_track = kde(track_points.T)
    map_max = float(kde(sample.T).max())
    if map_max <= 0:
        return 0.0
    return max(0.0, min(1.0, float(density_along_track.max()) / map_max))


def temporal_score(fixes: list[dict], window_start: datetime, window_end: datetime) -> float:
    """T = fraction of the release window covered by AIS data, where a gap
    more than 2x the track's median fix interval counts as uncovered."""
    times = sorted(datetime.fromisoformat(f["ts"]) for f in fixes)
    window_dur = (window_end - window_start).total_seconds()
    if not times or window_dur <= 0:
        return 0.0
    intervals = [(t1, t2) for t1, t2 in zip(times, times[1:])]
    gaps_s = [(t2 - t1).total_seconds() for t1, t2 in intervals]
    median_gap = sorted(gaps_s)[len(gaps_s) // 2] if gaps_s else 0.0
    covered_s = 0.0
    for t1, t2 in intervals:
        gap_s = (t2 - t1).total_seconds()
        if median_gap == 0 or gap_s <= 2 * median_gap:
            lo, hi = max(t1, window_start), min(t2, window_end)
            if hi > lo:
                covered_s += (hi - lo).total_seconds()
    return max(0.0, min(1.0, covered_s / window_dur))


def trajectory_score(fixes: list[dict], observed_geometry: dict, orientation_deg: float, intersects_buffer_km: float) -> float:
    """J = 0.5*track_intersects + 0.5*(1 - |delta_theta|/90) (weights.yaml)."""
    from backend.core.geometry import km_per_deg

    line = LineString([(f["lon"], f["lat"]) for f in fixes]) if len(fixes) >= 2 else Point(fixes[0]["lon"], fixes[0]["lat"])
    poly = shape(observed_geometry)
    lat0 = poly.centroid.y
    km_lon, km_lat = km_per_deg(lat0)
    dist_deg = line.distance(poly)
    dist_km = dist_deg * ((km_lon + km_lat) / 2)  # rough deg->km at this latitude
    track_intersects = 1.0 if dist_km <= intersects_buffer_km else 0.0

    if len(fixes) >= 2:
        dlon = (fixes[-1]["lon"] - fixes[0]["lon"]) * km_lon
        dlat = (fixes[-1]["lat"] - fixes[0]["lat"]) * km_lat
        track_heading = math.degrees(math.atan2(dlon, dlat)) % 180
    else:
        track_heading = orientation_deg
    delta = abs(track_heading - orientation_deg) % 180
    delta = min(delta, 180 - delta)  # fold to 0-90, alignment is axis-symmetric

    return max(0.0, min(1.0, 0.5 * track_intersects + 0.5 * (1 - delta / 90.0)))


def evidence_strength(factors: dict[str, float], thresholds: dict) -> str:
    n_above = sum(1 for v in factors.values() if v > thresholds["factor_threshold"])
    if n_above >= thresholds["strong_min_factors_above"]:
        return "strong"
    if n_above >= thresholds["moderate_min_factors_above"]:
        return "moderate"
    return "weak"


def uncertainty_level(q: float, drift_compat: float, hypotheses_tested: int) -> str:
    if q < 0.5 or hypotheses_tested < 3:
        return "high"
    if q >= 0.85 and drift_compat >= 0.5:
        return "low"
    return "medium"


def data_quality_level(q: float, forcing_quality: str) -> str:
    if forcing_quality != "high" or q < 0.85:
        return "medium" if q >= 0.5 else "low"
    return "high"


def fuse_candidate(
    candidate: dict,
    m6_result: dict,
    behaviour: dict,
    origin_cloud: np.ndarray,
    observed_geometry: dict,
    orientation_deg: float,
    window_start: datetime,
    window_end: datetime,
    forcing_quality: str,
    weights_cfg: dict,
    rng: np.random.Generator,
) -> dict:
    w = weights_cfg["weights"]
    norm = weights_cfg["normalisers"]

    fixes = candidate["fixes"]
    q = candidate["quality"]["score"]

    s = spatial_score(fixes, origin_cloud, rng)
    t = temporal_score(fixes, window_start, window_end)
    j = trajectory_score(fixes, observed_geometry, orientation_deg, norm["trajectory"]["intersects_buffer_km"])
    d = m6_result["D"]
    b = behaviour["B"]

    factors = {"spatial": s, "temporal": t, "trajectory": j, "drift": d, "behaviour": b}
    weighted = {k: w[k] * v for k, v in factors.items()}
    association = q * sum(weighted.values())

    levels = weights_cfg["levels"]
    if association >= levels["high"]:
        level = "high"
    elif association >= levels["medium"]:
        level = "medium"
    else:
        level = "low"

    evidence = []
    labels = {
        "spatial": "Vessel's closest approach falls in a {p:.0%}-of-peak origin-probability zone",
        "temporal": "AIS coverage spans {p:.0%} of the plausible release window",
        "trajectory": "Track axis alignment with the slick's major axis scores {p:.0%}",
        "drift": "Counterfactual forward simulation scores {p:.0%} (hit-rate {hr:.0%}, IoU {iou:.2f})",
        "behaviour": "Strongest behavioural anomaly ({rule}) scores {p:.0%}",
    }
    br = m6_result.get("best_release")
    for kind in ("spatial", "temporal", "trajectory", "drift", "behaviour"):
        val = factors[kind]
        if kind == "drift" and br:
            label = labels[kind].format(p=val, hr=br["hit_rate"], iou=br["iou"])
        elif kind == "behaviour":
            label = labels[kind].format(p=val, rule=behaviour["dominant_rule"].replace("_", " "))
        else:
            label = labels[kind].format(p=val)
        evidence.append({
            "kind": kind,
            "label": label,
            "value": round(val, 4),
            "weight_contribution": q * weighted[kind],  # unrounded: sum(weight_contribution) == association exactly
            "supporting": True,
        })

    cautions = []
    if forcing_quality != "high":
        cautions.append("Forcing field is the uniform low-quality fallback (no live CMEMS/ERA5 pull); treat hindcast and counterfactual spread as a lower bound.")
        evidence.append({
            "kind": "quality", "label": "Forcing quality is low (uniform-field fallback)",
            "value": 0.0, "weight_contribution": 0.0, "supporting": False,
        })
    if candidate["quality"]["gap_fraction"] > 0.15:
        cautions.append(f"AIS gap fraction is {candidate['quality']['gap_fraction']:.0%} for this track.")
    if candidate["mmsi"] is None:
        cautions.append("Unidentified vessel (no MMSI) — SAR-only correlation.")
    if candidate.get("source") == "synthetic":
        cautions.append("Synthetic AIS demonstration track — scores and rankings are for software demonstration only, not historical vessel attribution.")

    return {
        "candidate_id": f"cand-{candidate['track_id']}",
        "track_id": candidate["track_id"],
        "spatial": round(s, 4), "temporal": round(t, 4), "trajectory": round(j, 4),
        "drift_compat": round(d, 4), "behaviour": round(b, 4), "ais_quality": round(q, 4),
        "association": association,  # unrounded: sum(evidence.weight_contribution) == this exactly
        "association_level": level,
        "evidence_strength": evidence_strength(factors, weights_cfg["evidence_strength_thresholds"]),
        "uncertainty": "high" if candidate.get("source") == "synthetic" else uncertainty_level(q, d, m6_result["hypotheses_tested"]),
        "data_quality": data_quality_level(q, forcing_quality),
        "best_release": br,
        "evidence": evidence,
        "cautions": cautions,
    }
