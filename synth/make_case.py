"""synth/make_case.py — the ground-truth generator.

Produces a synthetic "twin": a true release point + time, a real forward-
advected observed slick (particle cloud -> alpha shape, not a drawn shape),
the true vessel's AIS track threaded through that release, N distractor
tracks with independent speeds/headings/gaps/loiter segments, and a
`ground_truth.json` answer key.

The pipeline (backend/cli.py) reads only `raw/observation_input.json` and
`raw/ais_feed.json` from this module's output. It never reads
`ground_truth.json` -- that file exists solely for synth/run_experiments.py
to score the pipeline's blind output afterwards.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import typer

from backend.core.drift import DriftConfig, advect
from backend.core.geometry import alpha_shape, polygon_area_km2
from synth.true_forcing import true_forcing

app = typer.Typer(add_completion=False)

# A fixed, clearly-synthetic reference clock -- not a real incident date.
# Only release timing (hours before this) varies per seed; this keeps every
# generated case reproducible for a given --seed.
REFERENCE_OBSERVED_AT = datetime(2030, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

DOMAIN_LON = (63.0, 64.0)
DOMAIN_LAT = (19.5, 20.3)
VESSEL_TYPES = ["tanker", "bulk_carrier", "cargo", "container_ship", "fishing_vessel"]


def km_per_deg(lat_deg: float) -> tuple[float, float]:
    km_lat = 111.32
    km_lon = 111.32 * max(math.cos(math.radians(lat_deg)), 0.15)
    return km_lon, km_lat


def _mmsi(rng: np.random.Generator) -> str:
    return str(int(rng.integers(200_000_000, 799_999_999)))


def synth_track(
    rng: np.random.Generator,
    track_id: str,
    anchor_lon: float,
    anchor_lat: float,
    anchor_time: datetime,
    window_start: datetime,
    window_end: datetime,
    gap_rate: float,
    loiter: bool,
    interval_min: float = 25.0,
    speed_kn_range: tuple[float, float] = (5.0, 15.0),
) -> dict:
    """A straight-line-with-noise track pinned to pass through
    (anchor_lon, anchor_lat) at anchor_time, spanning [window_start,
    window_end], with independently-random speed/heading, optional AIS gaps
    (fixes dropped with probability `gap_rate`) and an optional loiter
    segment (near-zero net displacement for 1-3 hours)."""

    speed_kn = float(rng.uniform(*speed_kn_range))
    heading_deg = float(rng.uniform(0, 360))
    speed_ms = speed_kn * 0.514444
    heading_rad = math.radians(heading_deg)
    v_east_ms = speed_ms * math.sin(heading_rad)
    v_north_ms = speed_ms * math.cos(heading_rad)
    km_lon, km_lat = km_per_deg(anchor_lat)
    dlon_per_s = v_east_ms / 1000.0 / km_lon
    dlat_per_s = v_north_ms / 1000.0 / km_lat

    times: list[datetime] = []
    t = window_start
    while t <= window_end:
        times.append(t)
        t += timedelta(minutes=interval_min)
    if anchor_time < window_start or anchor_time > window_end:
        anchor_time = max(window_start, min(anchor_time, window_end))
    times.append(anchor_time)
    times = sorted(set(times))

    loiter_start = loiter_end = None
    if loiter:
        span_s = (window_end - window_start).total_seconds()
        ls = window_start + timedelta(seconds=float(rng.uniform(0.15, 0.55)) * span_s)
        loiter_start = ls
        loiter_end = ls + timedelta(hours=float(rng.uniform(1.0, 3.0)))

    fixes = []
    for ti in times:
        dt_s = (ti - anchor_time).total_seconds()
        in_loiter = loiter_start is not None and loiter_start <= ti <= loiter_end
        if in_loiter:
            base_dt_s = (loiter_start - anchor_time).total_seconds()
            lon_i = anchor_lon + dlon_per_s * base_dt_s + float(rng.normal(0, 0.0004))
            lat_i = anchor_lat + dlat_per_s * base_dt_s + float(rng.normal(0, 0.0004))
            sog_i = max(0.05, float(rng.normal(0.4, 0.25)))
            cog_i = float(rng.uniform(0, 360))
        else:
            lon_i = anchor_lon + dlon_per_s * dt_s + float(rng.normal(0, 0.0007))
            lat_i = anchor_lat + dlat_per_s * dt_s + float(rng.normal(0, 0.0007))
            sog_i = max(0.3, float(rng.normal(speed_kn, 1.0)))
            cog_i = (heading_deg + float(rng.normal(0, 5))) % 360
        if ti != anchor_time and rng.uniform() < gap_rate:
            continue
        fixes.append({
            "ts": ti.isoformat(),
            "lon": round(lon_i, 6),
            "lat": round(lat_i, 6),
            "sog": round(sog_i, 2),
            "cog": round(cog_i, 1),
            "heading": round(cog_i, 1),
        })

    return {
        "track_id": track_id,
        "vessel_type": str(rng.choice(VESSEL_TYPES)),
        "fixes": fixes,
        "source": "synthetic",
        "_had_loiter": bool(loiter),
    }


def generate_regional_traffic(
    rng: np.random.Generator,
    center_lon: float,
    center_lat: float,
    window_start: datetime,
    window_end: datetime,
    n_tracks: int,
    gap_rate: float,
    loiter_rate: float,
) -> list[dict]:
    """A regional AIS traffic picture around (center_lon, center_lat) with no
    designated "true" vessel — used both for make_case's distractors (where a
    true vessel exists elsewhere) AND for backend/api's real-scene upload
    path (where there is no hidden answer to fabricate; every track here is
    an honest, unlabelled candidate, provenance.ais = 'synthetic' because
    real AIS ingest is deferred per ARCHITECTURE.md §0.1)."""
    km_lon, km_lat = km_per_deg(center_lat)
    tracks = []
    for i in range(n_tracks):
        dist_km = float(rng.uniform(2.0, 70.0))
        bearing = float(rng.uniform(0, 2 * math.pi))
        d_lon = center_lon + (dist_km * math.sin(bearing)) / km_lon
        d_lat = center_lat + (dist_km * math.cos(bearing)) / km_lat
        anchor_t = window_start + timedelta(
            seconds=float(rng.uniform(0, max((window_end - window_start).total_seconds(), 1.0)))
        )
        loiter = bool(rng.uniform() < loiter_rate)
        track = synth_track(
            rng, f"trk-dist-{i:02d}", d_lon, d_lat, anchor_t,
            window_start, window_end, gap_rate, loiter=loiter,
        )
        track["mmsi"] = _mmsi(rng)
        track.pop("_had_loiter", None)
        tracks.append(track)
    if tracks:
        tracks[0]["mmsi"] = None  # one unidentified / SAR-only candidate
    return tracks


@dataclass
class CaseResult:
    case_id: str
    out_dir: str
    true_mmsi: str
    true_track_id: str
    release_lon: float
    release_lat: float
    release_time: str
    observed_at: str
    observed_area_km2: float
    n_tracks: int


def make_case(
    case_id: str = "demo",
    lon: float | None = None,
    lat: float | None = None,
    release_time: datetime | None = None,
    duration_h: float = 20.0,
    n_distractors: int = 4,
    gap_rate: float = 0.10,
    loiter_rate: float = 0.30,
    seed: int = 42,
    out: Path = Path("cases/demo"),
    n_particles: int = 300,
) -> CaseResult:
    rng = np.random.default_rng(seed)
    observed_at = REFERENCE_OBSERVED_AT

    if lon is None:
        lon = float(rng.uniform(*DOMAIN_LON))
    if lat is None:
        lat = float(rng.uniform(*DOMAIN_LAT))
    if release_time is None:
        hours_before = float(rng.uniform(3.0, duration_h))
        release_time = observed_at - timedelta(hours=hours_before)

    # --- (b) forward-advect a small particle cloud -> real observed slick ---
    n0 = n_particles
    km_lon, km_lat = km_per_deg(lat)
    init_spread_km = 0.12
    jitter_km = rng.normal(0, init_spread_km, size=(n0, 2))
    particles0 = np.stack([
        lon + jitter_km[:, 0] / km_lon,
        lat + jitter_km[:, 1] / km_lat,
    ], axis=1)

    forcing = true_forcing(rng, lon, lat)
    drift_cfg = DriftConfig(windage=0.03, horizontal_diffusivity=3.0, timestep_s=600.0, engine="builtin")
    t0 = release_time.timestamp()
    t1 = observed_at.timestamp()
    final_particles = advect(particles0, t0, t1, forcing, drift_cfg, rng=rng)
    observed_polygon = alpha_shape(final_particles, alpha=0.35)
    area_km2 = polygon_area_km2(observed_polygon)

    # --- (c) true vessel track, threaded through the release ---
    true_mmsi = _mmsi(rng)
    true_track_id = "trk-true"
    track_window_start = release_time - timedelta(hours=float(rng.uniform(2.0, 5.0)))
    track_window_end = observed_at
    true_track = synth_track(
        rng, true_track_id, lon, lat, release_time,
        track_window_start, track_window_end, gap_rate, loiter=False,
    )
    true_track["mmsi"] = true_mmsi

    # --- distractors: some plausible, some not, per M5's spatial/temporal filters ---
    wide_start = release_time - timedelta(hours=10)
    distractors = generate_regional_traffic(
        rng, lon, lat, wide_start, observed_at, n_distractors, gap_rate, loiter_rate,
    )

    all_tracks = [true_track] + distractors
    for t in all_tracks:
        t.pop("_had_loiter", None)

    # --- write outputs ---
    out = Path(out)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    obs_geojson = {
        "type": "Polygon",
        "coordinates": [[[round(x, 6), round(y, 6)] for x, y in observed_polygon.exterior.coords]],
    }
    observation_input = {
        "spill_id": f"spill-{case_id}",
        "image_id": f"SYN-{case_id}-{seed}",
        "observed_at": observed_at.isoformat(),
        "geometry": obs_geojson,
    }
    (raw_dir / "observation_input.json").write_text(json.dumps(observation_input, indent=2))

    (raw_dir / "ais_feed.json").write_text(json.dumps(all_tracks, indent=2))

    ground_truth = {
        "case_id": case_id,
        "seed": seed,
        "true_mmsi": true_mmsi,
        "true_track_id": true_track_id,
        "release_lon": lon,
        "release_lat": lat,
        "release_time": release_time.isoformat(),
        "observed_at": observed_at.isoformat(),
        "observed_area_km2": area_km2,
        "n_distractors": n_distractors,
    }
    (out / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2))

    return CaseResult(
        case_id=case_id, out_dir=str(out), true_mmsi=true_mmsi,
        true_track_id=true_track_id, release_lon=lon, release_lat=lat,
        release_time=release_time.isoformat(), observed_at=observed_at.isoformat(),
        observed_area_km2=area_km2, n_tracks=len(all_tracks),
    )


@app.command()
def main(
    case_id: str = typer.Option("demo", "--case-id"),
    lon: float = typer.Option(None, "--lon"),
    lat: float = typer.Option(None, "--lat"),
    release_time: str = typer.Option(None, "--release-time", help="ISO-8601 UTC"),
    duration_h: float = typer.Option(20.0, "--duration-h"),
    n_distractors: int = typer.Option(4, "--n-distractors"),
    gap_rate: float = typer.Option(0.10, "--gap-rate"),
    loiter_rate: float = typer.Option(0.30, "--loiter-rate"),
    seed: int = typer.Option(42, "--seed"),
    out: Path = typer.Option(Path("cases/demo"), "--out"),
):
    rt = datetime.fromisoformat(release_time) if release_time else None
    result = make_case(
        case_id=case_id, lon=lon, lat=lat, release_time=rt, duration_h=duration_h,
        n_distractors=n_distractors, gap_rate=gap_rate, loiter_rate=loiter_rate,
        seed=seed, out=out,
    )
    typer.echo(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    app()
