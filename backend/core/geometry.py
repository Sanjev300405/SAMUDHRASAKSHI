"""Shared geometry helpers for M4 (hindcast) and M6 (counterfactual):
particle-cloud -> polygon footprint, and its area/IoU against another polygon.

ARCHITECTURE.md §5 M6 is explicit that a convex hull is "too generous and
will inflate every IoU" — this module's default footprint is a real
alpha-shape (Edelsbrunner-style: Delaunay triangulation, keep only triangles
whose circumradius is below 1/alpha, union the survivors), computed with
scipy.spatial.Delaunay + shapely only (no extra dependency).
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from scipy.spatial import Delaunay
from shapely.geometry import MultiPoint, Polygon
from shapely.ops import unary_union

FootprintMethod = Literal["alpha_shape", "convex_hull"]


def _circumradius(pts: np.ndarray) -> float:
    """Circumradius of the triangle formed by 3 (x, y) points."""
    a = np.linalg.norm(pts[1] - pts[2])
    b = np.linalg.norm(pts[0] - pts[2])
    c = np.linalg.norm(pts[0] - pts[1])
    s = (a + b + c) / 2.0
    area = max(s * (s - a) * (s - b) * (s - c), 1e-18) ** 0.5
    if area <= 1e-12:
        return float("inf")
    return (a * b * c) / (4.0 * area)


def alpha_shape(points: np.ndarray, alpha: float) -> Polygon:
    """Alpha-shape of a 2D point cloud. `alpha` is the Edelsbrunner alpha
    parameter: triangles with circumradius > 1/alpha are discarded before
    unioning the rest. Larger alpha -> tighter, more concave shape; alpha ->
    0 approaches the convex hull.
    """
    points = np.asarray(points, dtype=float)
    if len(points) < 4:
        return MultiPoint([tuple(p) for p in points]).convex_hull

    tri = Delaunay(points)
    max_r = float("inf") if alpha <= 0 else 1.0 / alpha
    triangles = []
    for simplex in tri.simplices:
        pts = points[simplex]
        if _circumradius(pts) <= max_r:
            triangles.append(Polygon(pts))

    if not triangles:
        # alpha too aggressive for this point density -- fail honestly
        # into the convex hull rather than returning an empty polygon.
        return MultiPoint([tuple(p) for p in points]).convex_hull

    shape = unary_union(triangles)
    if shape.geom_type == "MultiPolygon":
        shape = max(shape.geoms, key=lambda g: g.area)
    return shape


def footprint_polygon(points: np.ndarray, method: FootprintMethod, alpha: float) -> Polygon:
    if method == "convex_hull":
        import sys

        print(
            "WARNING: --footprint convex_hull inflates IoU relative to the true "
            "particle-cloud shape (ARCHITECTURE.md §5 M6) -- use for comparison "
            "only, not for reported attribution numbers.",
            file=sys.stderr,
        )
        return MultiPoint([tuple(p) for p in points]).convex_hull
    if method == "alpha_shape":
        return alpha_shape(points, alpha)
    raise ValueError(f"unknown footprint method: {method!r}")


def polygon_iou(a: Polygon, b: Polygon) -> float:
    if a.is_empty or b.is_empty:
        return 0.0
    inter = a.intersection(b).area
    union = a.union(b).area
    return inter / union if union > 0 else 0.0


def hit_rate(points: np.ndarray, polygon: Polygon) -> float:
    """Fraction of `points` (lon, lat) that fall inside `polygon`."""
    if len(points) == 0:
        return 0.0
    from shapely.geometry import Point
    from shapely.prepared import prep

    prepared = prep(polygon)
    inside = sum(1 for p in points if prepared.contains(Point(p[0], p[1])))
    return inside / len(points)


def km_per_deg(lat_deg: float) -> tuple[float, float]:
    """(km per degree longitude, km per degree latitude) at a given latitude."""
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * max(np.cos(np.radians(lat_deg)), 0.15)
    return km_per_deg_lon, km_per_deg_lat


def polygon_area_km2(polygon: Polygon) -> float:
    """Area of a lon/lat polygon in km^2, via an equirectangular correction
    at the polygon's centroid latitude. Exact for the small (few-km) extents
    this prototype's slicks have; would need a proper geodesic area for
    polygons spanning many degrees of latitude."""
    if polygon.is_empty:
        return 0.0
    lat0 = polygon.centroid.y
    km_lon, km_lat = km_per_deg(lat0)
    coords = np.array(polygon.exterior.coords)
    x_km = coords[:, 0] * km_lon
    y_km = coords[:, 1] * km_lat
    return float(Polygon(np.stack([x_km, y_km], axis=1)).area)
