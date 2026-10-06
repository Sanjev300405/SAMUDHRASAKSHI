"""backend/core/m3_characterise.py — ARCHITECTURE.md §5 M3.

Per §0.1's per-module prototype scope, M3 is "real: shapely geometry, cheap
and fully real" — the only module in this build that needs no simplifying
fallback, because it is pure geometry over whatever polygon M1/M2 hand it.

M1/M2 are not implemented as image-processing stages in this build: there is
no synthetic SAR raster, only the polygon `synth/make_case.py` produced by
forward-advecting real particles (§0.1's stated prototype scope for the
demo). `load_observation` is the honest stand-in for "M1/M2 already ran and
here is their output" — it does not threshold pixels because there are no
pixels, only the shape M2 would have output.

Two values this module cannot get from a real classifier (M2 is out of
scope, per §0.1) are approximated, transparently:

- `classification` is always "oil": this prototype's generator only ever
  produces genuine slicks, never look-alikes, so there is nothing for a
  classifier to distinguish.
- `confidence` uses solidity (alpha-shape area / convex-hull area) as a
  proxy: a more fragmented, irregular shape is a weaker detection signal in
  real segmentation systems too. This is a real, computed number from the
  actual polygon, not an invented constant — but it is a proxy for a missing
  classifier, not a classifier's own probability, and is documented as such.
- `age_class` uses observed area as a proxy for spreading-driven aging
  (larger slicks have had more time to spread) since this prototype has no
  multi-temporal imagery to measure fragmentation against, per §5 M3's
  intended method. Thresholds are documented below.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from shapely.geometry import shape

from backend.core.geometry import km_per_deg, polygon_area_km2

AGE_THRESHOLDS_KM2 = {"lt_6h": 3.0, "6_24h": 10.0}  # above 10.0 km2 -> gt_24h


def age_class_from_area(area_km2: float) -> str:
    if area_km2 < AGE_THRESHOLDS_KM2["lt_6h"]:
        return "lt_6h"
    if area_km2 < AGE_THRESHOLDS_KM2["6_24h"]:
        return "6_24h"
    return "gt_24h"


def characterise(geometry_geojson: dict) -> dict:
    """Real geometry from shapely — area, perimeter, length/width/orientation
    via the minimum rotated rectangle, circularity, and the two proxy fields
    documented in this module's docstring."""
    poly = shape(geometry_geojson)
    lat0 = poly.centroid.y
    km_lon, km_lat = km_per_deg(lat0)

    area_km2 = polygon_area_km2(poly)

    coords = list(poly.exterior.coords)
    perim_km = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        dx = (lon2 - lon1) * km_lon
        dy = (lat2 - lat1) * km_lat
        perim_km += math.hypot(dx, dy)

    mrr = poly.minimum_rotated_rectangle
    mrr_coords = list(mrr.exterior.coords)[:4]
    edge_lens_km = []
    edge_vecs = []
    for (lon1, lat1), (lon2, lat2) in zip(mrr_coords, mrr_coords[1:] + mrr_coords[:1]):
        dx = (lon2 - lon1) * km_lon
        dy = (lat2 - lat1) * km_lat
        edge_lens_km.append(math.hypot(dx, dy))
        edge_vecs.append((dx, dy))
    # two distinct edge lengths (opposite sides equal for a rectangle)
    length_km = max(edge_lens_km)
    width_km = min(edge_lens_km) if min(edge_lens_km) > 0 else length_km
    major_idx = edge_lens_km.index(length_km)
    dx, dy = edge_vecs[major_idx]
    orientation_deg = math.degrees(math.atan2(dx, dy)) % 180  # 0=north, clockwise

    circularity = (4 * math.pi * area_km2) / (perim_km ** 2) if perim_km > 0 else 0.0
    solidity = area_km2 / (polygon_area_km2(poly.convex_hull) or area_km2 or 1.0)
    confidence = max(0.5, min(0.98, solidity))

    return {
        "geometry": geometry_geojson,
        "area_km2": round(area_km2, 4),
        "perimeter_km": round(perim_km, 4),
        "length_km": round(length_km, 4),
        "width_km": round(width_km, 4),
        "centroid": (round(poly.centroid.x, 6), round(poly.centroid.y, 6)),
        "orientation_deg": round(orientation_deg, 2),
        "circularity": round(min(circularity, 1.0), 4),
        "classification": "oil",
        "confidence": round(confidence, 3),
        "age_class": age_class_from_area(area_km2),
    }


def load_observation(case_dir: Path) -> dict:
    """Stand-in for "M1/M2 already ran": reads the raw polygon + metadata
    synth produced and runs the real M3 characterisation over it."""
    raw = json.loads((Path(case_dir) / "raw" / "observation_input.json").read_text())
    char = characterise(raw["geometry"])
    return {
        "spill_id": raw["spill_id"],
        "image_id": raw["image_id"],
        "observed_at": raw["observed_at"],
        **char,
    }
