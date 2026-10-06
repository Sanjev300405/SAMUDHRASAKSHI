"""backend/core/raster.py — saves the real origin-probability KDE grid as a
.npy array (no PNG rendering dependency in scope; see backend/cli.py's module
docstring). Shared by the CLI and the API so both write the identical format.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.stats import gaussian_kde


def save_probability_grid(origin_cloud: np.ndarray, out_dir: Path, n: int = 60, max_sample: int = 3000) -> tuple[str, list]:
    assets_dir = Path(out_dir) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    grid_path = assets_dir / "opm_grid.npy"

    lon_min, lat_min = origin_cloud.min(axis=0)
    lon_max, lat_max = origin_cloud.max(axis=0)
    pad_lon = (lon_max - lon_min) * 0.1 or 0.01
    pad_lat = (lat_max - lat_min) * 0.1 or 0.01
    bounds = [lon_min - pad_lon, lat_min - pad_lat, lon_max + pad_lon, lat_max + pad_lat]

    xs = np.linspace(bounds[0], bounds[2], n)
    ys = np.linspace(bounds[1], bounds[3], n)
    xx, yy = np.meshgrid(xs, ys)
    sample = origin_cloud
    if len(sample) > max_sample:
        rng = np.random.default_rng(0)
        idx = rng.choice(len(sample), size=max_sample, replace=False)
        sample = sample[idx]
    kde = gaussian_kde(sample.T)
    grid = kde(np.stack([xx.ravel(), yy.ravel()])).reshape(xx.shape)
    grid = grid / grid.max()
    np.save(grid_path, grid.astype(np.float32))
    return str(grid_path.as_posix()), [float(b) for b in bounds]
