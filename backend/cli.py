"""backend/cli.py — ARCHITECTURE.md §8/§9. Orchestrates M3 -> M4 -> M5 -> M6 ->
M7 -> M8 into one CaseBundle, and exposes each stage standalone.

    python -m backend.cli run --case demo --out frontend/public/cases/demo/

Nothing here is hardcoded: every behavioural parameter is a YAML key
(config/weights.yaml) or a CLI flag, per §9.

Not implemented in this build, stated rather than faked (§0.1's own
"Deferred" list covers the first three; the fourth is this build's own
honest scope boundary):
  - M1/M2 as real image-processing stages (no synthetic SAR raster exists to
    threshold — synth/make_case.py's polygon IS M2's output, per §0.1).
  - report.pdf (WeasyPrint is not in this build's approved dependency list;
    `report` below emits export.geojson instead, which needs no new
    dependency).
  - assets.sar_png / assets.opm_png: no raster-rendering dependency (PIL/
    matplotlib/GDAL) is in scope. The origin probability grid IS saved for
    real, as a .npy array (`probability_raster_path`) — the frontend draws
    real vector geometry directly rather than a rendered raster, which is
    also why MapScene.tsx's own comments already say there is no raster
    asset in this prototype.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import typer

from backend.adapters.forcing import uniform_forcing
from backend.core.drift import Forcing
from backend.core.m3_characterise import load_observation
from backend.core.m4_hindcast import run_hindcast
from backend.core.m5_ais_recon import reconstruct
from backend.core.m6_counterfactual import run_counterfactual
from backend.core.m7_behaviour import behaviour_score
from backend.core.m8_fusion import fuse_candidate, load_weights
from backend.core.raster import save_probability_grid

app = typer.Typer(add_completion=False)


def _parse_range(s: str) -> tuple[float, float]:
    a, b = s.split(",")
    return float(a), float(b)


def _build_forcing(current_u, current_v, wind_u, wind_v) -> Forcing:
    return uniform_forcing(current_u=current_u, current_v=current_v, wind_u=wind_u, wind_v=wind_v)


def run_pipeline(
    case: str = "demo",
    case_dir: Path | None = None,
    out: Path = Path("frontend/public/cases/demo"),
    ensemble: int = 30,
    particles: int = 500,
    windage_range: tuple[float, float] = (0.02, 0.04),
    current_perturb: float = 0.15,
    release_interval_min: float = 12.0,
    particles_per_release: int = 100,
    hit_weight: float = 0.6,
    iou_weight: float = 0.4,
    footprint: str = "alpha_shape",
    alpha: float = 0.35,
    buffer_km: float = 25.0,
    max_speed_kn: float = 25.0,
    min_fixes: int = 5,
    weights_path: str = "config/weights.yaml",
    current_u: float = 0.15, current_v: float = 0.05, wind_u: float = 3.0, wind_v: float = -2.0,
    seed: int = 0,
) -> dict:
    case_dir = case_dir or Path("cases") / case
    forcing = _build_forcing(current_u, current_v, wind_u, wind_v)
    weights_cfg = load_weights(weights_path)

    observation = load_observation(case_dir)

    origin = run_hindcast(
        observation, forcing, ensemble=ensemble, particles=particles,
        windage_range=windage_range, current_perturb=current_perturb, seed=seed,
    )
    origin_cloud = origin.pop("_origin_cloud")
    raster_path, opm_bounds = save_probability_grid(origin_cloud, Path(out))
    origin["probability_raster_path"] = raster_path

    raw_tracks = json.loads((case_dir / "raw" / "ais_feed.json").read_text())
    candidates = reconstruct(raw_tracks, origin, buffer_km=buffer_km, max_speed_kn=max_speed_kn, min_fixes=min_fixes)
    if not candidates:
        raise RuntimeError(
            "M5 filtered every AIS track out (none were spatially/temporally/physically "
            "reachable). Widen --buffer-km / --max-speed-kn or check the case's inputs — "
            "refusing to fabricate a candidate list."
        )

    window_start = datetime.fromisoformat(origin["window_start"])
    window_end = datetime.fromisoformat(origin["window_end"])
    observed_at = datetime.fromisoformat(observation["observed_at"])

    m6_results = run_counterfactual(
        candidates, window_start, window_end, observed_at, observation["geometry"], forcing,
        release_interval_min=release_interval_min, particles_per_release=particles_per_release,
        hit_weight=hit_weight, iou_weight=iou_weight, footprint_method=footprint, alpha=alpha, seed=seed,
    )

    rng = np.random.default_rng(seed)
    scored = []
    for cand in candidates:
        beh = behaviour_score(cand["fixes"], window_start, window_end)
        scored.append(fuse_candidate(
            cand, m6_results[cand["track_id"]], beh, origin_cloud, observation["geometry"],
            observation["orientation_deg"], window_start, window_end, origin["forcing_quality"],
            weights_cfg, rng,
        ))
    scored.sort(key=lambda c: c["association"], reverse=True)

    bundle = {
        "case_id": case,
        "provenance": {"sar": "synthetic", "forcing": "synthetic", "ais": "synthetic"},
        "observation": {**observation, "provenance": {"sar": "synthetic", "forcing": "synthetic", "ais": "synthetic"}},
        "origin": origin,
        "tracks": candidates,
        "candidates": scored,
        "assets": {
            "sar_png": "assets/sar_not_rendered.png",  # see module docstring: no raster pipeline in scope
            "opm_png": "assets/opm_not_rendered.png",
            "opm_bounds": opm_bounds,
        },
        "config_snapshot": {
            "weights": weights_cfg["weights"],
            "drift": {
                "ensemble_size": ensemble,
                "particles_per_release": particles_per_release,
                "windage_range": list(windage_range),
                "footprint_method": footprint,
                "drift_compat_norm": f"D = {hit_weight}*hit_rate + {iou_weight}*iou",
            },
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return bundle


def _validate_with_contracts(bundle: dict) -> None:
    from contracts.contracts import CaseBundle

    CaseBundle.model_validate(bundle)


@app.command()
def run(
    case: str = typer.Option("demo", "--case"),
    out: Path = typer.Option(Path("frontend/public/cases/demo"), "--out"),
    ensemble: int = typer.Option(30, "--ensemble"),
    particles: int = typer.Option(500, "--particles"),
    windage_range: str = typer.Option("0.02,0.04", "--windage-range"),
    current_perturb: float = typer.Option(0.15, "--current-perturb"),
    release_interval_min: float = typer.Option(12.0, "--release-interval-min"),
    particles_per_release: int = typer.Option(100, "--particles-per-release"),
    hit_weight: float = typer.Option(0.6, "--hit-weight"),
    iou_weight: float = typer.Option(0.4, "--iou-weight"),
    footprint: str = typer.Option("alpha_shape", "--footprint"),
    alpha: float = typer.Option(0.35, "--alpha"),
    buffer_km: float = typer.Option(25.0, "--buffer-km"),
    max_speed_kn: float = typer.Option(25.0, "--max-speed-kn"),
    min_fixes: int = typer.Option(5, "--min-fixes"),
    weights: str = typer.Option("config/weights.yaml", "--weights"),
    ais_source: str = typer.Option("synthetic", "--ais-source"),
    drift_engine: str = typer.Option("builtin", "--drift-engine"),
    seed: int = typer.Option(0, "--seed"),
):
    if ais_source != "synthetic":
        raise typer.BadParameter("only --ais-source synthetic is implemented in this build (real/provided ingest is deferred, per ARCHITECTURE.md §0.1)")
    if drift_engine != "builtin":
        typer.echo(f"NOTE: --drift-engine {drift_engine} requested; see backend/core/drift.py's docstring for what this does and does not support.", err=True)

    bundle = run_pipeline(
        case=case, out=out, ensemble=ensemble, particles=particles,
        windage_range=_parse_range(windage_range), current_perturb=current_perturb,
        release_interval_min=release_interval_min, particles_per_release=particles_per_release,
        hit_weight=hit_weight, iou_weight=iou_weight, footprint=footprint, alpha=alpha,
        buffer_km=buffer_km, max_speed_kn=max_speed_kn, min_fixes=min_fixes,
        weights_path=weights, seed=seed,
    )
    _validate_with_contracts(bundle)

    out.mkdir(parents=True, exist_ok=True)
    (out / "bundle.json").write_text(json.dumps(bundle, indent=2, default=str))
    typer.echo(f"wrote {out / 'bundle.json'}")

    mmsi_by_track = {t["track_id"]: (t["mmsi"] or "no-mmsi") for t in bundle["tracks"]}
    typer.echo("candidates ranked (track_id, mmsi, association):")
    for c in bundle["candidates"]:
        typer.echo(f"  {c['track_id']:<14} {mmsi_by_track.get(c['track_id'], 'unknown'):<12} {c['association']:.4f}  ({c['association_level']})")


@app.command()
def detect(case: str = typer.Option("demo", "--case")):
    obs = load_observation(Path("cases") / case)
    typer.echo(json.dumps(obs, indent=2, default=str))


@app.command()
def hindcast(case: str = typer.Option("demo", "--case"), ensemble: int = 30, particles: int = 500, seed: int = 0):
    obs = load_observation(Path("cases") / case)
    forcing = uniform_forcing()
    origin = run_hindcast(obs, forcing, ensemble=ensemble, particles=particles, seed=seed)
    origin.pop("_origin_cloud")
    typer.echo(json.dumps(origin, indent=2, default=str))


@app.command()
def traffic(case: str = typer.Option("demo", "--case"), buffer_km: float = 25.0, max_speed_kn: float = 25.0, min_fixes: int = 5, seed: int = 0):
    case_dir = Path("cases") / case
    obs = load_observation(case_dir)
    forcing = uniform_forcing()
    origin = run_hindcast(obs, forcing, ensemble=8, particles=150, seed=seed)
    origin.pop("_origin_cloud")
    raw_tracks = json.loads((case_dir / "raw" / "ais_feed.json").read_text())
    candidates = reconstruct(raw_tracks, origin, buffer_km=buffer_km, max_speed_kn=max_speed_kn, min_fixes=min_fixes)
    typer.echo(json.dumps(candidates, indent=2, default=str))


@app.command()
def simulate(case: str = typer.Option("demo", "--case"), out: Path = typer.Option(Path("frontend/public/cases/demo"), "--out")):
    bundle = run_pipeline(case=case, out=out)
    typer.echo(json.dumps(bundle["candidates"], indent=2, default=str))


@app.command()
def report(case: str = typer.Option("demo", "--case"), out: Path = typer.Option(Path("frontend/public/cases/demo"), "--out")):
    """Emits export.geojson (no PDF -- WeasyPrint is not an approved dependency in this build)."""
    bundle_path = out / "bundle.json"
    if not bundle_path.exists():
        raise typer.BadParameter(f"{bundle_path} does not exist -- run `run` first")
    bundle = json.loads(bundle_path.read_text())
    features = [{"type": "Feature", "geometry": bundle["observation"]["geometry"], "properties": {"kind": "observed_slick"}}]
    for c in bundle["candidates"]:
        if c["best_release"]:
            features.append({
                "type": "Feature", "geometry": c["best_release"]["simulated_geometry"],
                "properties": {"kind": "simulated_slick", "track_id": c["track_id"], "association": c["association"]},
            })
    geojson = {"type": "FeatureCollection", "features": features}
    (out / "export.geojson").write_text(json.dumps(geojson, indent=2))
    typer.echo(f"wrote {out / 'export.geojson'}")


if __name__ == "__main__":
    app()
