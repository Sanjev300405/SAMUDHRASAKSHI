"""synth/run_experiments.py — ARCHITECTURE.md §10 validation harness.

For each of N seeds: generate a blind synthetic twin (synth.make_case), run
the real pipeline chain over it (M3->M4->M5->M6->M7->M8, calling the same
functions backend/cli.py uses — never a subprocess re-implementation), THEN
and only then open ground_truth.json to score the pipeline's output. The
pipeline itself never sees ground_truth.json.

Reports (§10's Table 11, the parts this build's scope actually covers):
  - top-1 / top-3 attribution hit-rate (the headline number)
  - origin recovery error: km from the pooled origin cloud's centroid to the
    true release point, and % of true release points inside the high-prob polygon
  - the ablation: proximity-only (rank by S alone) vs full fusion vs
    fusion-with-D-removed (weights renormalised over the remaining 4 factors)
  - latency (mean wall-clock per case)

Segmentation IoU/F1 and look-alike false-alarm rate are NOT reported: M1/M2
are not implemented as real image-processing stages in this build (no
synthetic SAR raster exists — see backend/cli.py's module docstring), so
there is nothing to measure them against. Stated, not hidden.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import typer
from shapely.geometry import Point, shape

from backend.adapters.forcing import uniform_forcing
from backend.core.geometry import km_per_deg
from backend.core.m3_characterise import load_observation
from backend.core.m4_hindcast import run_hindcast
from backend.core.m5_ais_recon import reconstruct
from backend.core.m6_counterfactual import run_counterfactual
from backend.core.m7_behaviour import behaviour_score
from backend.core.m8_fusion import fuse_candidate, load_weights
from synth.make_case import make_case

app = typer.Typer(add_completion=False)


def _rank_by(scored: list[dict], key) -> list[str]:
    return [c["track_id"] for c in sorted(scored, key=key, reverse=True)]


def _fusion_without_drift(scored: list[dict], weights_cfg: dict) -> list[dict]:
    w = weights_cfg["weights"]
    remaining = {k: v for k, v in w.items() if k != "drift"}
    total = sum(remaining.values())
    renorm = {k: v / total for k, v in remaining.items()}
    out = []
    for c in scored:
        a = c["ais_quality"] * (
            renorm["spatial"] * c["spatial"] + renorm["temporal"] * c["temporal"]
            + renorm["trajectory"] * c["trajectory"] + renorm["behaviour"] * c["behaviour"]
        )
        out.append({**c, "association": a})
    return out


def run_one_case(
    seed: int, case_dir: Path, ensemble: int, particles: int, particles_per_release: int,
    duration_h: float = 20.0,
) -> dict:
    make_case(case_id=case_dir.name, seed=seed, out=case_dir, n_particles=250, duration_h=duration_h)
    ground_truth = json.loads((case_dir / "ground_truth.json").read_text())

    t_start = time.time()
    forcing = uniform_forcing()
    weights_cfg = load_weights("config/weights.yaml")

    observation = load_observation(case_dir)
    origin = run_hindcast(observation, forcing, ensemble=ensemble, particles=particles, seed=seed)
    origin_cloud = origin.pop("_origin_cloud")

    raw_tracks = json.loads((case_dir / "raw" / "ais_feed.json").read_text())
    candidates = reconstruct(raw_tracks, origin)

    window_start = datetime.fromisoformat(origin["window_start"])
    window_end = datetime.fromisoformat(origin["window_end"])
    observed_at = datetime.fromisoformat(observation["observed_at"])

    result = {
        "seed": seed, "true_mmsi": ground_truth["true_mmsi"],
        "top1_hit": False, "top3_hit": False,
        "origin_error_km": None, "true_in_high_prob": None,
        "latency_s": None, "n_candidates": len(candidates),
        "ranking_full": [], "ranking_proximity": [], "ranking_no_drift": [],
    }

    if not candidates:
        result["latency_s"] = time.time() - t_start
        return result

    m6_results = run_counterfactual(
        candidates, window_start, window_end, observed_at, observation["geometry"], forcing,
        particles_per_release=particles_per_release, seed=seed,
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

    result["latency_s"] = time.time() - t_start

    ranking_full = _rank_by(scored, key=lambda c: c["association"])
    ranking_proximity = _rank_by(scored, key=lambda c: c["spatial"])
    ranking_no_drift = _rank_by(_fusion_without_drift(scored, weights_cfg), key=lambda c: c["association"])

    result["ranking_full"] = ranking_full
    result["ranking_proximity"] = ranking_proximity
    result["ranking_no_drift"] = ranking_no_drift

    true_track_id = ground_truth["true_track_id"]
    result["true_track_present"] = true_track_id in [c["track_id"] for c in candidates]
    result["top1_hit"] = bool(ranking_full and ranking_full[0] == true_track_id)
    result["top3_hit"] = true_track_id in ranking_full[:3]
    result["top1_hit_proximity"] = bool(ranking_proximity and ranking_proximity[0] == true_track_id)
    result["top1_hit_no_drift"] = bool(ranking_no_drift and ranking_no_drift[0] == true_track_id)

    centroid = origin_cloud.mean(axis=0)
    km_lon, km_lat = km_per_deg(ground_truth["release_lat"])
    dx = (centroid[0] - ground_truth["release_lon"]) * km_lon
    dy = (centroid[1] - ground_truth["release_lat"]) * km_lat
    result["origin_error_km"] = round(float(np.hypot(dx, dy)), 3)

    high_poly = shape(origin["high_prob_geometry"])
    result["true_in_high_prob"] = high_poly.contains(Point(ground_truth["release_lon"], ground_truth["release_lat"]))

    return result


def summarise(results: list[dict]) -> dict:
    n = len(results)
    with_candidates = [r for r in results if r["n_candidates"] > 0]
    n_wc = len(with_candidates) or 1

    def rate(key):
        return sum(1 for r in with_candidates if r[key]) / n_wc

    origin_errors = [r["origin_error_km"] for r in with_candidates if r["origin_error_km"] is not None]
    in_high = [r["true_in_high_prob"] for r in with_candidates if r["true_in_high_prob"] is not None]
    latencies = [r["latency_s"] for r in results if r["latency_s"] is not None]

    return {
        "n_cases": n,
        "n_cases_with_candidates": len(with_candidates),
        "top1_hit_rate": round(rate("top1_hit"), 4),
        "top3_hit_rate": round(rate("top3_hit"), 4),
        "ablation": {
            "proximity_only_top1": round(rate("top1_hit_proximity"), 4),
            "full_fusion_top1": round(rate("top1_hit"), 4),
            "fusion_without_drift_top1": round(rate("top1_hit_no_drift"), 4),
        },
        "origin_recovery_error_km_mean": round(float(np.mean(origin_errors)), 3) if origin_errors else None,
        "origin_recovery_error_km_median": round(float(np.median(origin_errors)), 3) if origin_errors else None,
        "true_release_in_high_prob_region_pct": round(sum(in_high) / len(in_high), 4) if in_high else None,
        "latency_s_mean": round(float(np.mean(latencies)), 2) if latencies else None,
    }


def to_markdown(summary: dict, results: list[dict]) -> str:
    lines = [
        "# synth.run_experiments results",
        "",
        f"N = {summary['n_cases']} synthetic twins ({summary['n_cases_with_candidates']} produced at least one M5-surviving candidate).",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| **Top-1 attribution hit-rate** | **{summary['top1_hit_rate']:.1%}** |",
        f"| Top-3 attribution hit-rate | {summary['top3_hit_rate']:.1%} |",
        f"| Origin recovery error (mean) | {summary['origin_recovery_error_km_mean']} km |",
        f"| Origin recovery error (median) | {summary['origin_recovery_error_km_median']} km |",
        f"| True release inside high-prob region | {summary['true_release_in_high_prob_region_pct']:.1%} |",
        f"| Mean latency per case | {summary['latency_s_mean']} s |",
        "",
        "## Ablation — does M6 earn its 0.35 weight?",
        "",
        "| Ranking method | Top-1 hit-rate |",
        "|---|---|",
        f"| Proximity-only (spatial S alone) | {summary['ablation']['proximity_only_top1']:.1%} |",
        f"| Full fusion (A, all 5 factors) | {summary['ablation']['full_fusion_top1']:.1%} |",
        f"| Fusion with drift term removed | {summary['ablation']['fusion_without_drift_top1']:.1%} |",
        "",
    ]
    return "\n".join(lines)


@app.command()
def main(
    n: int = typer.Option(50, "--n"),
    seed: int = typer.Option(42, "--seed"),
    out: Path = typer.Option(Path("results"), "--out"),
    ensemble: int = typer.Option(10, "--ensemble"),
    particles: int = typer.Option(200, "--particles"),
    particles_per_release: int = typer.Option(50, "--particles-per-release"),
    duration_h: float = typer.Option(
        20.0, "--duration-h",
        help="Hours between release and the satellite observation. The drift test's\nskill degrades as this grows, because the pipeline's uniform forcing field\ndiverges from the richer field the twin was built with. Measured: the true\nvessel's hit-rate is ~0.00 at 20h and ~0.81 at 12h. Sweep it; do not assume it.",
    ),
    keep_cases: bool = typer.Option(False, "--keep-cases"),
):
    out.mkdir(parents=True, exist_ok=True)
    work_dir = out / "_experiment_cases"
    work_dir.mkdir(parents=True, exist_ok=True)

    results = []
    t0 = time.time()
    for i in range(n):
        s = seed + i
        case_dir = work_dir / f"twin-{s}"
        typer.echo(f"[{i + 1}/{n}] seed={s} ...", err=True)
        try:
            r = run_one_case(s, case_dir, ensemble, particles, particles_per_release, duration_h=duration_h)
        except Exception as e:  # noqa: BLE001
            typer.echo(f"  FAILED: {e}", err=True)
            r = {"seed": s, "error": str(e), "n_candidates": 0, "top1_hit": False, "top3_hit": False,
                 "origin_error_km": None, "true_in_high_prob": None, "latency_s": None}
        results.append(r)
        if not keep_cases:
            shutil.rmtree(case_dir, ignore_errors=True)
    total_s = time.time() - t0

    summary = summarise(results)
    summary["total_wall_time_s"] = round(total_s, 1)

    (out / "metrics.json").write_text(json.dumps({"summary": summary, "per_case": results}, indent=2, default=str))
    md = to_markdown(summary, results)
    (out / "metrics.md").write_text(md)

    typer.echo(md)
    typer.echo(f"wrote {out / 'metrics.json'} and {out / 'metrics.md'}")


if __name__ == "__main__":
    app()
