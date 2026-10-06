"""backend/core/m4_hindcast.py — ARCHITECTURE.md §5 M4, backward ensemble.

**The collapse rule (§5 M4 demands this be written down explicitly, since a
backward run yields a 3-D field origin(x, y, t) but OriginEstimate is a 2-D
map plus a separate time window):**

1. The time window [window_start, window_end] is derived from `age_class`
   alone (open decision #1, §13):
     lt_6h  -> horizon H = 6h
     6_24h  -> horizon H = 24h
     gt_24h -> horizon H = 48h
     unknown -> horizon H = 30h
   window_start = observed_at - H
   window_end   = observed_at - 0.5h   (a slick cannot have released in the
                                         instant it was imaged)
   This is a documented simplification of "age class + last-clean-image":
   this prototype has no multi-revisit imagery, so age_class alone sets H.

2. Each ensemble member is run backward from observed_at to window_start
   (the full horizon), snapshotting particle positions every 30 minutes.
   Snapshots whose time falls inside [window_start, window_end] are pooled
   across ALL members into one 2-D point cloud — this pooled cloud IS "particle
   density integrated over the plausible sub-window" from the spec. A 2-D
   KDE over that pooled cloud is the origin probability map; contours are
   read off by ranking pooled particles by their own KDE density (top 15%
   density -> high-probability region, top 50% -> medium), then alpha-shaping
   each subset — this avoids needing a grid-marching-squares dependency while
   still producing a real density-derived polygon, not a drawn one.

M6 (counterfactual) MUST use the identical Forcing as this module — see
backend/cli.py, which builds one Forcing per run and passes it to both.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Callable, Sequence

import numpy as np
from scipy.stats import gaussian_kde

from backend.core.drift import DriftConfig, Forcing, advect
from backend.core.geometry import alpha_shape, km_per_deg

HORIZON_H = {"lt_6h": 6.0, "6_24h": 24.0, "gt_24h": 48.0, "unknown": 30.0}
SNAPSHOT_INTERVAL_S = 1800.0
HIGH_DENSITY_QUANTILE = 0.85  # top 15% densest pooled particles
MED_DENSITY_QUANTILE = 0.50  # top 50%


def time_window(observed_at: datetime, age_class: str) -> tuple[datetime, datetime]:
    h = HORIZON_H.get(age_class, HORIZON_H["unknown"])
    window_start = observed_at - timedelta(hours=h)
    window_end = observed_at - timedelta(hours=0.5)
    return window_start, window_end


def _seed_in_polygon(polygon_coords: Sequence[tuple[float, float]], n: int, rng: np.random.Generator) -> np.ndarray:
    from shapely.geometry import Point, Polygon

    poly = Polygon(polygon_coords)
    minx, miny, maxx, maxy = poly.bounds
    pts = []
    guard = 0
    while len(pts) < n and guard < n * 200:
        guard += 1
        x = rng.uniform(minx, maxx)
        y = rng.uniform(miny, maxy)
        if poly.contains(Point(x, y)):
            pts.append((x, y))
    if len(pts) < n:  # degenerate/tiny polygon: fall back to centroid jitter
        c = poly.centroid
        extra = rng.normal(0, 1e-4, size=(n - len(pts), 2)) + [c.x, c.y]
        pts.extend(map(tuple, extra))
    return np.array(pts)


MAX_KDE_POINTS = 3000  # gaussian_kde evaluation is O(n^2); pooled clouds at
# realistic ensemble*particles*snapshots (tens of thousands) would make an
# unsubsampled KDE evaluation impractically slow. A few-thousand-point random
# subsample is a standard, honest way to keep a density ESTIMATE tractable —
# it changes the KDE's variance, not its target, and the alpha-shape only
# needs a representative sample of the high-density region regardless.
MAX_ALPHA_POINTS = 1200  # alpha-shape's Delaunay+union cost grows with point
# count; a polygon outline needs enough boundary-relevant points to be a good
# approximation, not literally every particle.


def _density_subset_polygon(points: np.ndarray, quantile: float, alpha: float, rng: np.random.Generator) -> np.ndarray:
    if len(points) < 5:
        return points
    if len(points) > MAX_KDE_POINTS:
        idx = rng.choice(len(points), size=MAX_KDE_POINTS, replace=False)
        sample = points[idx]
    else:
        sample = points
    kde = gaussian_kde(sample.T)
    density = kde(sample.T)
    threshold = np.quantile(density, quantile)
    subset = sample[density >= threshold]
    if len(subset) > MAX_ALPHA_POINTS:
        idx = rng.choice(len(subset), size=MAX_ALPHA_POINTS, replace=False)
        subset = subset[idx]
    return subset


def run_hindcast(
    observation: dict,
    forcing: Forcing,
    ensemble: int = 30,
    particles: int = 500,
    windage_range: tuple[float, float] = (0.02, 0.04),
    current_perturb: float = 0.15,
    timestep_s: float = 600.0,
    alpha: float = 0.35,
    seed: int = 0,
    progress_cb: "Callable[[int, int, str], None] | None" = None,
) -> dict:
    """`progress_cb(current, total, message)` is called once per ensemble
    member (e.g. "Hindcast: member 12 of 30") — used by backend/api to report
    determinate progress on the async /hindcast endpoint. Optional; CLI and
    test callers are unaffected."""
    rng = np.random.default_rng(seed)
    observed_at = datetime.fromisoformat(observation["observed_at"])
    age_class = observation["age_class"]
    window_start, window_end = time_window(observed_at, age_class)
    horizon_h = HORIZON_H.get(age_class, HORIZON_H["unknown"])

    polygon_coords = observation["geometry"]["coordinates"][0]
    pooled: list[np.ndarray] = []

    t_end_epoch = observed_at.timestamp()
    t_start_epoch = (observed_at - timedelta(hours=horizon_h)).timestamp()
    window_start_epoch = window_start.timestamp()
    window_end_epoch = window_end.timestamp()

    for member in range(ensemble):
        if progress_cb:
            progress_cb(member + 1, ensemble, f"Hindcast: member {member + 1} of {ensemble}")
        windage_k = float(rng.uniform(*windage_range))
        perturb_k = float(rng.uniform(-current_perturb, current_perturb))
        member_forcing = _perturb_forcing(forcing, perturb_k)
        cfg = DriftConfig(windage=windage_k, horizontal_diffusivity=2.0, timestep_s=timestep_s, engine="builtin")

        pts = _seed_in_polygon(polygon_coords, particles, rng)
        t = t_end_epoch
        while t > t_start_epoch:
            t_next = max(t - SNAPSHOT_INTERVAL_S, t_start_epoch)
            pts = advect(pts, t, t_next, member_forcing, cfg, rng=rng)
            t = t_next
            if window_start_epoch <= t <= window_end_epoch:
                pooled.append(pts.copy())

    origin_cloud = np.concatenate(pooled, axis=0) if pooled else _seed_in_polygon(polygon_coords, particles, rng)

    centroid = origin_cloud.mean(axis=0)
    km_lon, km_lat = km_per_deg(centroid[1])
    dx_km = (origin_cloud[:, 0] - centroid[0]) * km_lon
    dy_km = (origin_cloud[:, 1] - centroid[1]) * km_lat
    spread_km = float(np.sqrt(np.mean(dx_km ** 2 + dy_km ** 2)))

    high_pts = _density_subset_polygon(origin_cloud, HIGH_DENSITY_QUANTILE, alpha, rng)
    med_pts = _density_subset_polygon(origin_cloud, MED_DENSITY_QUANTILE, alpha, rng)
    high_poly = alpha_shape(high_pts, alpha)
    med_poly = alpha_shape(med_pts, alpha * 0.6)  # looser alpha for the broader region

    def to_geojson(poly):
        if poly.geom_type != "Polygon" or poly.is_empty:
            poly = poly.convex_hull
        return {"type": "Polygon", "coordinates": [[[round(x, 6), round(y, 6)] for x, y in poly.exterior.coords]]}

    return {
        "spill_id": observation["spill_id"],
        "probability_raster_path": None,  # filled by cli.py after saving the grid
        "high_prob_geometry": to_geojson(high_poly),
        "medium_prob_geometry": to_geojson(med_poly),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "ensemble_size": ensemble,
        "spread_km": round(spread_km, 3),
        "forcing_quality": forcing.quality,
        "_origin_cloud": origin_cloud,  # consumed by cli.py for the raster + by M8 for spatial scoring
    }


def _perturb_forcing(forcing: Forcing, perturb: float) -> Forcing:
    base_current = forcing.current

    def perturbed_current(lon, lat, t):
        u, v = base_current(lon, lat, t)
        return u * (1 + perturb), v * (1 + perturb)

    return Forcing(
        current=perturbed_current,
        wind=forcing.wind,
        quality=forcing.quality,
        uniform=forcing.uniform,
        uniform_current_uv=(
            (forcing.uniform_current_uv[0] * (1 + perturb), forcing.uniform_current_uv[1] * (1 + perturb))
            if forcing.uniform_current_uv else None
        ),
        uniform_wind_uv=forcing.uniform_wind_uv,
    )
