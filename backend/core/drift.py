"""backend/core/drift.py — the physics engine shared by M4 (backward hindcast)
and M6 (forward counterfactual). ARCHITECTURE.md §5 / ADR-005.

One interface, two engines, selected by `DriftConfig.engine`:

`builtin` (the default). Pure numpy RK4 Lagrangian particle advection with
explicit wind-drift ("windage") and a stochastic horizontal-diffusivity term
(a random walk added each step, variance = 2*kappa*dt, the standard
Fokker-Planck discretisation for constant horizontal diffusivity). This is
the same numerical family OpenDrift's own OceanDrift module uses internally
(RK4 advection + diffusion) — the difference is packaging, not physics.

Why `builtin` is the default rather than `opendrift`: OpenDrift's binary
dependencies (GDAL, NetCDF4, Cartopy) do not reliably `pip install` on
Windows outside a conda environment, and this project's environment is a
plain venv (ARCHITECTURE.md environment note). Requiring conda here would be
a real, unforced schedule risk for a documented capability a from-scratch
RK4 scheme already provides. The RK4 + explicit-windage-and-diffusivity
scheme is scientifically defensible and is what gets reported honestly in
this module's docstring, not hidden behind a library name.

`opendrift`. Delegates to a real `opendrift.models.oceandrift.OceanDrift` run
when the package is importable, mapping our uniform `Forcing` (ADR-003's
allowed uniform-current-and-wind fallback — see backend/adapters/forcing.py)
onto OpenDrift's built-in `reader_constant`. If a spatially-varying Forcing
is passed to the opendrift engine, or the package is not importable, this
raises a clear, loud error — engines are never silently substituted for one
another.
"""

from __future__ import annotations

import dataclasses
from typing import Callable, Literal

import numpy as np

KM_PER_DEG_LAT = 111.32

VelocityFn = Callable[[np.ndarray, np.ndarray, float], tuple[np.ndarray, np.ndarray]]


@dataclasses.dataclass(frozen=True)
class Forcing:
    """Provider-agnostic forcing. `current` and `wind` each map
    (lon_array, lat_array, t_epoch_s) -> (u, v) in m/s, east/north positive.
    `uniform` is True when current/wind do not vary with (lon, lat, t) —
    such a Forcing can be delegated to OpenDrift's `reader_constant`.
    `quality` is surfaced directly to OriginEstimate.forcing_quality.
    """

    current: VelocityFn
    wind: VelocityFn
    quality: Literal["high", "medium", "low"]
    uniform: bool
    # only meaningful when uniform=True; used by the opendrift bridge
    uniform_current_uv: tuple[float, float] | None = None
    uniform_wind_uv: tuple[float, float] | None = None


@dataclasses.dataclass(frozen=True)
class DriftConfig:
    windage: float = 0.03  # fraction of wind velocity added to current drift
    horizontal_diffusivity: float = 2.0  # m^2/s
    timestep_s: float = 600.0  # magnitude only; direction comes from t1 vs t0
    engine: Literal["builtin", "opendrift"] = "builtin"


def _deg_per_m(lat_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Local metres->degrees conversion factors at each particle's latitude."""
    dlat_per_m = np.full_like(lat_deg, 1.0 / (KM_PER_DEG_LAT * 1000.0))
    cos_lat = np.cos(np.radians(lat_deg))
    cos_lat = np.clip(cos_lat, 0.15, None)  # guard the poles; irrelevant at our scale
    dlon_per_m = 1.0 / (KM_PER_DEG_LAT * 1000.0 * cos_lat)
    return dlon_per_m, dlat_per_m


def _velocity_ms(lon: np.ndarray, lat: np.ndarray, t: float, forcing: Forcing, windage: float):
    cu, cv = forcing.current(lon, lat, t)
    wu, wv = forcing.wind(lon, lat, t)
    return cu + windage * wu, cv + windage * wv


def _rk4_deg_step(lon: np.ndarray, lat: np.ndarray, t: float, dt_s: float, forcing: Forcing, windage: float):
    def deriv(lon_i, lat_i, t_i):
        u, v = _velocity_ms(lon_i, lat_i, t_i, forcing, windage)
        dlon_per_m, dlat_per_m = _deg_per_m(lat_i)
        return u * dlon_per_m, v * dlat_per_m

    k1lon, k1lat = deriv(lon, lat, t)
    k2lon, k2lat = deriv(lon + 0.5 * dt_s * k1lon, lat + 0.5 * dt_s * k1lat, t + 0.5 * dt_s)
    k3lon, k3lat = deriv(lon + 0.5 * dt_s * k2lon, lat + 0.5 * dt_s * k2lat, t + 0.5 * dt_s)
    k4lon, k4lat = deriv(lon + dt_s * k3lon, lat + dt_s * k3lat, t + dt_s)
    new_lon = lon + (dt_s / 6.0) * (k1lon + 2 * k2lon + 2 * k3lon + k4lon)
    new_lat = lat + (dt_s / 6.0) * (k1lat + 2 * k2lat + 2 * k3lat + k4lat)
    return new_lon, new_lat


def advect(
    particles: np.ndarray,
    t0: float | np.ndarray,
    t1: float,
    forcing: Forcing,
    cfg: DriftConfig,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Advect `particles` ([N,2] lon/lat) from epoch seconds t0 to t1.

    `t0` may be a scalar (every particle starts at the same time — M4's
    backward hindcast) or an [N] array of per-particle start times (M6's
    counterfactual: ADR-005 requires ALL (vessel, release_time) hypotheses
    batched into one call, tagged by particle, rather than one call per
    hypothesis — a particle whose own t0 is later than the current
    integration time simply has not "left the dock" yet and stays at its
    seed position until the global clock reaches it).

    Scalar t0: t1 < t0 runs backward (M4); t1 > t0 runs forward (synth
    ground truth). Array t0: only forward (t1 >= every t0) is supported,
    which is the only direction M6 needs.

    Returns the [N,2] final positions.
    """
    if particles.shape[0] == 0:
        return particles.copy()
    if cfg.engine == "opendrift":
        return _advect_opendrift(particles, t0, t1, forcing, cfg)
    if cfg.engine != "builtin":
        raise ValueError(f"unknown drift engine: {cfg.engine!r}")

    if rng is None:
        rng = np.random.default_rng()

    lon = particles[:, 0].astype(float).copy()
    lat = particles[:, 1].astype(float).copy()

    t0_arr = np.asarray(t0, dtype=float)
    if t0_arr.ndim == 0:
        total_s = t1 - float(t0_arr)
        if total_s == 0:
            return np.stack([lon, lat], axis=1)
        direction = 1.0 if total_s > 0 else -1.0
        dt_s = direction * abs(cfg.timestep_s)
        n_full_steps = int(abs(total_s) // abs(cfg.timestep_s))
        remainder_s = total_s - n_full_steps * dt_s

        t = float(t0_arr)
        for _ in range(n_full_steps):
            lon, lat = _diffuse_step(lon, lat, t, dt_s, forcing, cfg, rng)
            t += dt_s
        if remainder_s != 0:
            lon, lat = _diffuse_step(lon, lat, t, remainder_s, forcing, cfg, rng)
        return np.stack([lon, lat], axis=1)

    # Array t0: per-particle release times, all advancing forward to the
    # same t1 in one batched call (ADR-005).
    if np.any(t0_arr > t1):
        raise ValueError("array t0 requires every start time <= t1 (forward only)")
    t0_arr = np.broadcast_to(t0_arr, lon.shape).astype(float).copy()
    global_t = float(t0_arr.min())
    step_s = abs(cfg.timestep_s)
    while global_t < t1 - 1e-9:
        step_end = min(global_t + step_s, t1)
        local_dt = np.clip(step_end - np.maximum(global_t, t0_arr), 0.0, None)
        local_t = np.maximum(global_t, t0_arr)
        lon, lat = _diffuse_step(lon, lat, local_t, local_dt, forcing, cfg, rng)
        global_t = step_end
    return np.stack([lon, lat], axis=1)


def _diffuse_step(lon, lat, t, dt_s, forcing, cfg, rng):
    lon, lat = _rk4_deg_step(lon, lat, t, dt_s, forcing, cfg.windage)
    # Random-walk horizontal diffusion: std = sqrt(2*kappa*|dt|) in metres,
    # the standard discretisation of a constant-diffusivity Fokker-Planck term.
    # dt_s may be a per-particle array (zero for not-yet-released particles),
    # which correctly gives them zero diffusion too.
    step_std_m = np.sqrt(2.0 * cfg.horizontal_diffusivity * np.abs(np.asarray(dt_s, dtype=float)))
    # scale=0 for any (scalar or per-particle) entry yields exactly 0 noise —
    # no branch needed; this also correctly zeroes diffusion for
    # not-yet-released particles in the array-t0 (M6) path.
    dlon_per_m, dlat_per_m = _deg_per_m(lat)
    noise_x_m = rng.normal(0.0, step_std_m, size=lon.shape)
    noise_y_m = rng.normal(0.0, step_std_m, size=lat.shape)
    lon = lon + noise_x_m * dlon_per_m
    lat = lat + noise_y_m * dlat_per_m
    return lon, lat


def _advect_opendrift(particles: np.ndarray, t0: float, t1: float, forcing: Forcing, cfg: DriftConfig) -> np.ndarray:
    try:
        from opendrift.models.oceandrift import OceanDrift
        from opendrift.readers import reader_constant
    except ImportError as e:
        raise RuntimeError(
            "drift-engine=opendrift was requested but the `opendrift` package is "
            "not importable in this environment. OpenDrift's native dependencies "
            "(GDAL, NetCDF4) do not reliably pip-install on Windows outside a "
            "conda environment; this project's venv does not provide them. "
            "Install OpenDrift in a conda env, or use --drift-engine builtin "
            "(the default). Not silently falling back."
        ) from e

    if not forcing.uniform:
        raise RuntimeError(
            "The opendrift engine bridge in this prototype only maps a uniform "
            "Forcing (ADR-003's allowed uniform-current-and-wind fallback) onto "
            "OpenDrift's reader_constant. A spatially-varying Forcing has no "
            "bridge implemented here — use --drift-engine builtin, which handles "
            "any Forcing callable directly."
        )

    import datetime as _dt

    cu, cv = forcing.uniform_current_uv
    wu, wv = forcing.uniform_wind_uv

    o = OceanDrift(loglevel=50)
    o.add_reader(reader_constant.Reader({"x_sea_water_velocity": cu, "y_sea_water_velocity": cv}))
    o.add_reader(reader_constant.Reader({"x_wind": wu, "y_wind": wv}))
    o.set_config("drift:wind_drift_factor", cfg.windage)
    o.set_config("drift:horizontal_diffusivity", cfg.horizontal_diffusivity)
    o.set_config("general:coastline_action", "none")
    o.seed_elements(
        lon=particles[:, 0], lat=particles[:, 1],
        time=_dt.datetime.utcfromtimestamp(t0),
    )
    duration_s = t1 - t0
    o.run(
        duration=_dt.timedelta(seconds=abs(duration_s)),
        time_step=int(np.sign(duration_s)) * abs(cfg.timestep_s),
    )
    lon_final = o.elements.lon
    lat_final = o.elements.lat
    return np.stack([lon_final, lat_final], axis=1)
