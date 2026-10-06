"""synth/true_forcing.py — the ocean the synthetic world actually has.

This is deliberately RICHER than backend/adapters/forcing.py's uniform
fallback: a meandering-jet analytic current (a background flow plus a
sinusoidal meander term, the standard toy field used to test Lagrangian
tracking schemes — see e.g. Bower 1991) plus a steady wind that differs
slightly from the pipeline's default guess.

The pipeline never imports this module. It is used only by
synth/make_case.py to advect the TRUE release forward into the observed
slick. The resulting mismatch between this field and the pipeline's uniform
estimate is intentional and load-bearing: it is the same gap a real system
has between the true ocean and a reanalysis product, and it is why M4/M6
skill in this build is measured, not asserted.
"""

from __future__ import annotations

import numpy as np

from backend.core.drift import Forcing


def true_forcing(rng: np.random.Generator, lon0: float, lat0: float) -> Forcing:
    """A per-case-randomised meandering jet, centred near (lon0, lat0)."""

    u0 = rng.uniform(0.05, 0.20)  # background zonal current, m/s
    v0 = rng.uniform(-0.05, 0.10)  # background meridional current, m/s
    amp = rng.uniform(0.08, 0.20)  # meander amplitude, m/s
    wavelength_deg = rng.uniform(0.15, 0.35)  # meander wavelength, degrees
    period_s = rng.uniform(8, 16) * 3600.0  # meander period, seconds
    k = 2 * np.pi / wavelength_deg
    omega = 2 * np.pi / period_s

    wind_u = rng.uniform(2.0, 5.0) * rng.choice([-1, 1])
    wind_v = rng.uniform(1.5, 4.0) * rng.choice([-1, 1])

    def current(lon: np.ndarray, lat: np.ndarray, t: float):
        u = u0 + amp * np.sin(k * (lat - lat0) + omega * t)
        v = v0 + amp * np.cos(k * (lon - lon0) + omega * t)
        return u, v

    def wind(lon: np.ndarray, lat: np.ndarray, t: float):
        return np.full_like(lon, wind_u), np.full_like(lat, wind_v)

    return Forcing(current=current, wind=wind, quality="high", uniform=False)
