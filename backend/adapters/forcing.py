"""backend/adapters/forcing.py — provider-agnostic ingress for ocean current
and wind fields, per ARCHITECTURE.md §3's repository layout.

Only the uniform-field fallback is implemented in this build. Real ERA5 /
CMEMS / HYCOM ingest is explicitly deferred (ARCHITECTURE.md §0.1, "Deferred"
list) — that is a stated limitation, not a hidden one. The uniform field is
itself an *allowed* fallback per §0.1's table ("Uniform current + wind behind the
forcing.py adapter, labelled in the UI") and ADR-003, not a shortcut invented
for this prototype: a real system without live reanalysis access degrades to
exactly this, and reports `forcing_quality: "low"` honestly rather than
pretending otherwise.

This is why M4/M6 in this build measure real, sometimes-mediocre skill: the
pipeline's estimate of the ocean is deliberately cruder than the richer
synthetic field `synth/make_case.py` uses to generate ground truth (see that
module's docstring) — the same gap a real system has between a reanalysis
product and the true ocean.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from backend.core.drift import Forcing


def uniform_forcing(
    current_u: float = 0.15,
    current_v: float = 0.05,
    wind_u: float = 3.0,
    wind_v: float = -2.0,
) -> Forcing:
    """A constant current + wind field, in m/s, east/north positive.

    Defaults are a plausible-order-of-magnitude regional estimate (tens of
    cm/s current, a few m/s wind) standing in for an unavailable CMEMS/ERA5
    pull -- override via CLI flags for a specific case.
    """

    def current(lon: np.ndarray, lat: np.ndarray, t: float):
        return np.full_like(lon, current_u), np.full_like(lat, current_v)

    def wind(lon: np.ndarray, lat: np.ndarray, t: float):
        return np.full_like(lon, wind_u), np.full_like(lat, wind_v)

    return Forcing(
        current=current,
        wind=wind,
        quality="low",
        uniform=True,
        uniform_current_uv=(current_u, current_v),
        uniform_wind_uv=(wind_u, wind_v),
    )


def sampled_forcing(samples: list[dict]) -> Forcing:
    """Build a time-varying field from archived current/wind samples.

    Input records use UTC epoch seconds plus lon/lat and east/north velocities
    in m/s. Each particle uses the nearest archived sample in space and time.
    This is deliberately a nearest-neighbour replay (not a gridded
    interpolation); callers should report the source and sampling resolution.
    """
    if not samples:
        raise ValueError("at least one archived forcing sample is required")
    times = np.asarray([
        float(s["time_s"]) if "time_s" in s else float(s["ts_epoch"])
        for s in samples
    ], dtype=float)
    unique_times = np.unique(times)
    lat_scale = max(float(np.cos(np.radians(np.mean([s["lat"] for s in samples])))), 0.15)
    spatial = {}
    values = {}
    for sample_time in unique_times:
        indices = np.flatnonzero(times == sample_time)
        points = np.asarray([
            [float(samples[i]["lon"]) * lat_scale, float(samples[i]["lat"])]
            for i in indices
        ])
        spatial[float(sample_time)] = (cKDTree(points), indices)
        values[float(sample_time)] = {
            key: np.asarray([float(samples[i][key]) for i in indices])
            for key in ("current_u", "current_v", "wind_u", "wind_v")
        }

    def lookup(lon: np.ndarray, lat: np.ndarray, t: float, u_key: str, v_key: str):
        times_at = np.asarray(t, dtype=float)

        def nearest_times(requested):
            pos = np.searchsorted(unique_times, requested)
            before_pos = np.clip(pos - 1, 0, len(unique_times) - 1)
            after_pos = np.clip(pos, 0, len(unique_times) - 1)
            before = unique_times[before_pos]
            after = unique_times[after_pos]
            return np.where(requested - before <= after - requested, before, after)

        if times_at.ndim == 0:
            sample_time = float(nearest_times(times_at))
            tree, _ = spatial[sample_time]
            _, idx = tree.query(np.column_stack([lon * lat_scale, lat]), k=1)
            return values[sample_time][u_key][idx], values[sample_time][v_key][idx]

        # M6 advances particles whose release times differ, so its integration
        # clock is a per-particle array. Resolve each particle to the nearest
        # archived time, then query the matching spatial tree in groups.
        requested = np.broadcast_to(times_at, np.shape(lon))
        chosen = nearest_times(requested)
        out_u = np.empty(np.shape(lon), dtype=float)
        out_v = np.empty(np.shape(lat), dtype=float)
        points = np.column_stack([lon * lat_scale, lat])
        for sample_time in np.unique(chosen):
            mask = chosen == sample_time
            tree, _ = spatial[float(sample_time)]
            _, idx = tree.query(points[mask], k=1)
            out_u[mask] = values[float(sample_time)][u_key][idx]
            out_v[mask] = values[float(sample_time)][v_key][idx]
        return out_u, out_v

    def current(lon: np.ndarray, lat: np.ndarray, t: float):
        return lookup(lon, lat, t, "current_u", "current_v")

    def wind(lon: np.ndarray, lat: np.ndarray, t: float):
        return lookup(lon, lat, t, "wind_u", "wind_v")

    return Forcing(current=current, wind=wind, quality="medium", uniform=False)
