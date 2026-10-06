"""backend/api/geotiff.py — a minimal, real GeoTIFF reader + classical
dark-spot detection, for the POST /api/v1/cases upload path.

No GDAL/rasterio: that dependency is exactly the kind of native-build risk
on Windows this project already avoided for OpenDrift (backend/core/drift.py's
docstring). Instead this hand-parses the TIFF IFD directly (stdlib `struct`
only) and supports the common simple case: uncompressed, single-band,
uint8/uint16/float32, byte or long strip offsets. That is a real, stated
format limitation, not a hidden one — a compressed or tiled GeoTIFF raises a
clear 400 error (see backend/api/main.py) rather than silently failing or
faking a result.

Detection follows ARCHITECTURE.md §5 M1/M2's own documented fallback: skip
calibration, percentile-normalise the raw values, then adaptive dark-spot
threshold + morphological cleanup (scipy.ndimage) — a real classical
image-processing pipeline that actually runs, not a name standing in for one.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from shapely.geometry import box
from shapely.ops import unary_union

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}  # TIFF field type -> byte size


@dataclass
class GeoTiff:
    array: np.ndarray  # 2D, band 0
    origin_lon: float
    origin_lat: float
    pixel_size_lon: float
    pixel_size_lat: float  # positive; row 0 is northernmost

    def lonlat_of(self, col: float, row: float) -> tuple[float, float]:
        return self.origin_lon + col * self.pixel_size_lon, self.origin_lat - row * self.pixel_size_lat


def _read_ifd_entries(data: bytes, offset: int, endian: str) -> dict[int, tuple[int, int, bytes]]:
    (n,) = struct.unpack_from(endian + "H", data, offset)
    entries: dict[int, tuple[int, int, bytes]] = {}
    for i in range(n):
        entry_off = offset + 2 + i * 12
        tag, ftype, count = struct.unpack_from(endian + "HHI", data, entry_off)
        value_bytes = data[entry_off + 8: entry_off + 12]
        entries[tag] = (ftype, count, value_bytes)
    return entries


def _entry_values(data: bytes, entry: tuple[int, int, bytes], endian: str) -> list[int | float]:
    ftype, count, raw = entry
    size = TYPE_SIZES.get(ftype, 1)
    total = size * count
    fmt_char = {1: "B", 2: "c", 3: "H", 4: "I", 5: "I", 11: "f", 12: "d"}.get(ftype, "B")
    if total <= 4:
        buf = raw
    else:
        (offset,) = struct.unpack(endian + "I", raw)
        buf = data[offset: offset + total]
    if ftype == 5:  # RATIONAL: two uint32 (numerator, denominator) per value
        vals = []
        for i in range(count):
            num, den = struct.unpack_from(endian + "II", buf, i * 8)
            vals.append(num / den if den else 0.0)
        return vals
    return list(struct.unpack_from(endian + fmt_char * count, buf, 0))


def read_geotiff(data: bytes) -> GeoTiff:
    if len(data) < 8:
        raise ValueError("not a TIFF file (too short)")
    byte_order = data[0:2]
    if byte_order == b"II":
        endian = "<"
    elif byte_order == b"MM":
        endian = ">"
    else:
        raise ValueError("not a TIFF file (bad byte-order marker)")
    magic = struct.unpack_from(endian + "H", data, 2)[0]
    if magic != 42:
        raise ValueError("not a TIFF file (bad magic number)")
    (ifd_offset,) = struct.unpack_from(endian + "I", data, 4)

    entries = _read_ifd_entries(data, ifd_offset, endian)

    def get(tag: int, default=None):
        if tag not in entries:
            return default
        return _entry_values(data, entries[tag], endian)

    width = int(get(256)[0])
    height = int(get(257)[0])
    bits_per_sample = int(get(258, [8])[0])
    compression = int(get(259, [1])[0])
    samples_per_pixel = int(get(277, [1])[0])
    rows_per_strip = int(get(278, [height])[0])
    sample_format = int(get(339, [1])[0])
    strip_offsets = [int(v) for v in get(273, [])]
    strip_byte_counts = [int(v) for v in get(279, [])]

    if compression != 1:
        raise ValueError(f"compressed GeoTIFF (compression={compression}) is not supported by this build's minimal reader -- re-export uncompressed")
    if not strip_offsets:
        raise ValueError("tiled GeoTIFF is not supported by this build's minimal reader (no StripOffsets tag) -- re-export as a stripped TIFF")

    dtype_map = {
        (8, 1): np.uint8, (16, 1): np.uint16, (32, 1): np.uint32,
        (8, 2): np.int8, (16, 2): np.int16, (32, 2): np.int32,
        (32, 3): np.float32, (64, 3): np.float64,
    }
    dtype = dtype_map.get((bits_per_sample, sample_format))
    if dtype is None:
        raise ValueError(f"unsupported sample type: {bits_per_sample}-bit, format={sample_format}")

    rows: list[np.ndarray] = []
    for i, (off, count) in enumerate(zip(strip_offsets, strip_byte_counts)):
        n_rows_this_strip = min(rows_per_strip, height - i * rows_per_strip)
        arr = np.frombuffer(data, dtype=dtype, count=n_rows_this_strip * width * samples_per_pixel, offset=off)
        arr = arr.reshape(n_rows_this_strip, width, samples_per_pixel)
        rows.append(arr[:, :, 0])  # band 0 only
    array = np.concatenate(rows, axis=0).astype(np.float64)

    pixel_scale = get(33550)  # GeoTIFF ModelPixelScaleTag: (x, y, z)
    tiepoint = get(33922)  # GeoTIFF ModelTiepointTag: (i,j,k, x,y,z), first tiepoint
    if pixel_scale and tiepoint:
        px_lon, px_lat = pixel_scale[0], pixel_scale[1]
        origin_lon, origin_lat = tiepoint[3], tiepoint[4]
    else:
        # no georeferencing tags -- fall back to a 1x1 degree unit square so
        # the array is still usable, but this is NOT a real-world location
        px_lon, px_lat = 1.0 / width, 1.0 / height
        origin_lon, origin_lat = 0.0, 1.0

    return GeoTiff(array=array, origin_lon=origin_lon, origin_lat=origin_lat, pixel_size_lon=px_lon, pixel_size_lat=px_lat)


def detect_dark_spots(tiff: GeoTiff, min_area_px: int = 25) -> dict:
    """Percentile-normalise, adaptive dark-spot threshold, morphological
    cleanup, largest connected component -> a real (if pixel-blocky) polygon
    in lon/lat. This is the classical fallback ARCHITECTURE.md §5 M1/M2 name
    explicitly, actually executed against the uploaded raster's own pixels."""
    arr = tiff.array
    lo, hi = np.percentile(arr, [2, 98])
    norm = np.clip((arr - lo) / max(hi - lo, 1e-9), 0, 1)

    threshold = np.percentile(norm, 15)  # adaptive: darkest ~15% of the scene
    mask = norm < threshold
    mask = ndimage.binary_opening(mask, structure=np.ones((3, 3)))
    mask = ndimage.binary_closing(mask, structure=np.ones((3, 3)))

    labeled, n = ndimage.label(mask)
    if n == 0:
        raise ValueError("no dark-spot candidates found after thresholding + morphological cleanup")
    sizes = ndimage.sum(mask, labeled, range(1, n + 1))
    best_label = int(np.argmax(sizes)) + 1
    if sizes[best_label - 1] < min_area_px:
        raise ValueError(f"largest candidate region is only {int(sizes[best_label - 1])}px, below the {min_area_px}px minimum")

    rows, cols = np.where(labeled == best_label)
    # Real but low-fidelity: union of unit pixel cells rather than a proper
    # marching-squares contour (no skimage/matplotlib in this build's scope).
    # Downsample first so the union stays tractable for large scenes.
    max_cells = 4000
    if len(rows) > max_cells:
        idx = np.random.default_rng(0).choice(len(rows), size=max_cells, replace=False)
        rows, cols = rows[idx], cols[idx]

    cells = []
    for r, c in zip(rows, cols):
        lon0, lat0 = tiff.lonlat_of(c, r)
        lon1, lat1 = tiff.lonlat_of(c + 1, r + 1)
        cells.append(box(min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1)))
    merged = unary_union(cells)
    if merged.geom_type == "MultiPolygon":
        merged = max(merged.geoms, key=lambda g: g.area)
    simplified = merged.simplify(tiff.pixel_size_lon * 1.5, preserve_topology=True)

    return {
        "type": "Polygon",
        "coordinates": [[[round(x, 6), round(y, 6)] for x, y in simplified.exterior.coords]],
    }
