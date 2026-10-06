"""backend/core/m6_counterfactual.py — ARCHITECTURE.md §5 M6 + ADR-005. The
differentiator: for every candidate vessel, ask "would ITS oil have made
THIS slick?" by really re-running the physics forward from its track.

ADR-005 batching, taken literally: every (candidate, release_time) hypothesis
is seeded as a tagged block of particles, and ALL of them — across every
candidate and every sampled release time — are advected in exactly ONE call
to backend.core.drift.advect(), using its per-particle t0 array support (see
that module's docstring). This function never loops advect() per hypothesis.

Two specification gaps ARCHITECTURE.md §5 M6 names explicitly, resolved here:

1. hit_rate + iou -> D combination: D = hit_weight*hit_rate + iou_weight*iou,
   defaults 0.6/0.4 (both CLI-overridable). hit_rate rewards raw coverage of
   the observed slick; iou additionally penalises a hypothesis whose
   footprint is much larger than the slick (high hit_rate, poor precision) —
   weighting hit_rate higher reflects that missing the slick entirely is a
   worse sign than a moderately oversized footprint, given this prototype's
   diffusivity is itself a rough estimate.
2. particle-cloud -> polygon: alpha-shape (backend.core.geometry), default
   alpha=0.35, NOT convex hull (which the spec calls out as inflating IoU).

**Using the identical Forcing as M4 is mandatory** (§5 M6) — enforced by the
caller (backend/cli.py) constructing one Forcing per run and passing it to
both m4_hindcast.run_hindcast and this module's run_counterfactual.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

import numpy as np
from shapely.geometry import shape

from backend.core.drift import DriftConfig, Forcing, advect
from backend.core.geometry import footprint_polygon, hit_rate as hit_rate_fn, polygon_iou


def _interpolate_position(fixes: list[dict], t: datetime) -> tuple[float, float] | None:
    times = [datetime.fromisoformat(f["ts"]) for f in fixes]
    if not times or t < times[0] or t > times[-1]:
        return None
    for i in range(len(times) - 1):
        if times[i] <= t <= times[i + 1]:
            span = (times[i + 1] - times[i]).total_seconds()
            frac = 0.0 if span == 0 else (t - times[i]).total_seconds() / span
            lon = fixes[i]["lon"] + frac * (fixes[i + 1]["lon"] - fixes[i]["lon"])
            lat = fixes[i]["lat"] + frac * (fixes[i + 1]["lat"] - fixes[i]["lat"])
            return lon, lat
    return None


def _sample_release_times(window_start: datetime, window_end: datetime, interval_min: float) -> list[datetime]:
    times = []
    t = window_start
    step = timedelta(minutes=interval_min)
    while t <= window_end:
        times.append(t)
        t += step
    if not times:
        times = [window_start]
    return times


def run_counterfactual(
    candidates: list[dict],
    window_start: datetime,
    window_end: datetime,
    observed_at: datetime,
    observed_geometry: dict,
    forcing: Forcing,
    release_interval_min: float = 12.0,
    particles_per_release: int = 100,
    hit_weight: float = 0.6,
    iou_weight: float = 0.4,
    footprint_method: str = "alpha_shape",
    alpha: float = 0.35,
    timestep_s: float = 600.0,
    seed: int = 0,
    progress_cb: "Callable[[int, int, str], None] | None" = None,
) -> dict[str, dict]:
    """Returns {track_id: {"D": float, "best_release": {...} | None,
    "hypotheses_tested": int}}.

    `progress_cb(current, total, message)`: the batched advect() call is one
    shot by design (ADR-005) so it can't report intermediate progress itself;
    progress is instead reported across the three real phases — seeding
    hypotheses, the single batched advection, and per-hypothesis scoring
    (which IS iterable) — used by backend/api's async /simulate endpoint.
    """
    rng = np.random.default_rng(seed)
    observed_polygon = shape(observed_geometry)
    release_times = _sample_release_times(window_start, window_end, release_interval_min)
    total_hyp_estimate = max(1, len(candidates) * len(release_times))

    if progress_cb:
        progress_cb(0, total_hyp_estimate, f"Simulate: seeding {len(candidates)} candidates x {len(release_times)} release times")

    # --- build ONE big tagged particle batch across every hypothesis ---
    all_particles: list[np.ndarray] = []
    all_t0: list[np.ndarray] = []
    hypotheses: list[tuple[str, datetime, float, float]] = []  # (track_id, t_k, lon, lat)

    for cand in candidates:
        for t_k in release_times:
            pos = _interpolate_position(cand["fixes"], t_k)
            if pos is None:
                continue
            lon, lat = pos
            jitter = rng.normal(0, 0.0008, size=(particles_per_release, 2))
            pts = np.stack([lon + jitter[:, 0], lat + jitter[:, 1]], axis=1)
            all_particles.append(pts)
            all_t0.append(np.full(particles_per_release, t_k.timestamp()))
            hypotheses.append((cand["track_id"], t_k, lon, lat))

    results: dict[str, dict] = {c["track_id"]: {"D": 0.0, "best_release": None, "hypotheses_tested": 0} for c in candidates}

    if not all_particles:
        return results

    particles = np.concatenate(all_particles, axis=0)
    t0_arr = np.concatenate(all_t0, axis=0)
    t1 = observed_at.timestamp()
    cfg = DriftConfig(windage=0.03, horizontal_diffusivity=2.0, timestep_s=timestep_s, engine="builtin")

    if progress_cb:
        progress_cb(0, len(hypotheses), f"Simulate: running batched advection ({len(particles)} particles, one call)")

    # THE single batched call — every candidate, every release time, one shot.
    final_positions = advect(particles, t0_arr, t1, forcing, cfg, rng=rng)

    # --- partition by tag and score each hypothesis ---
    best_d: dict[str, float] = {}
    offset = 0
    for i, (track_id, t_k, lon, lat) in enumerate(hypotheses):
        if progress_cb:
            progress_cb(i + 1, len(hypotheses), f"Simulate: scoring hypothesis {i + 1} of {len(hypotheses)}")
        block = final_positions[offset: offset + particles_per_release]
        offset += particles_per_release

        h_rate = hit_rate_fn(block, observed_polygon)
        footprint = footprint_polygon(block, footprint_method, alpha)
        iou = polygon_iou(footprint, observed_polygon)
        d_k = hit_weight * h_rate + iou_weight * iou

        results[track_id]["hypotheses_tested"] += 1
        if d_k >= best_d.get(track_id, -1.0):
            best_d[track_id] = d_k
            geom = footprint if footprint.geom_type == "Polygon" and not footprint.is_empty else footprint.convex_hull
            results[track_id]["D"] = round(d_k, 4)
            results[track_id]["best_release"] = {
                "time": t_k.isoformat(),
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "hit_rate": round(h_rate, 4),
                "iou": round(iou, 4),
                "simulated_geometry": {
                    "type": "Polygon",
                    "coordinates": [[[round(x, 6), round(y, 6)] for x, y in geom.exterior.coords]],
                },
            }

    return results
