"""backend/api/main.py — ARCHITECTURE.md §8.1's endpoints, each calling real
backend module code. Every route either runs the real stage or raises — none
fabricate a response when the real stage cannot be run from what it received.

    uvicorn backend.api.main:app --reload

In-memory, single-process case store (`_CASES`) carries each case's
intermediate stage outputs (observation, origin + its particle cloud,
candidates) between the separate stage endpoints within one server session —
this is a demo server per ARCHITECTURE.md's own scope, not a production
multi-worker deployment.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import math

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from backend.adapters.forcing import sampled_forcing, uniform_forcing
from backend.api import geotiff, jobs
from backend.api.live_data import fetch_live_conditions, fetch_noaa_incidents, search_sentinel1
from backend.api.pdf import build_report_pdf
from backend.core.m3_characterise import characterise, load_observation
from backend.core.m4_hindcast import run_hindcast
from backend.core.m5_ais_recon import reconstruct
from backend.core.m6_counterfactual import run_counterfactual
from backend.core.m7_behaviour import behaviour_score
from backend.core.m8_fusion import fuse_candidate, load_weights
from backend.core.raster import save_probability_grid
from contracts.contracts import CaseBundle
from synth.make_case import generate_regional_traffic, make_case

app = FastAPI(title="SAMUDRA SAKSHI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo server; a real deployment would pin this down
    allow_methods=["*"],
    allow_headers=["*"],
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CASES_ROOT = REPO_ROOT / "cases"
PUBLIC_CASES_ROOT = REPO_ROOT / "frontend" / "public" / "cases"
WEIGHTS_PATH = str(REPO_ROOT / "config" / "weights.yaml")

_CASES: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _case_store(case_id: str) -> dict[str, Any]:
    with _lock:
        store = _CASES.setdefault(case_id, {})
    return store


def _out_dir(case_id: str) -> Path:
    d = PUBLIC_CASES_ROOT / case_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _case_dir(case_id: str) -> Path:
    return CASES_ROOT / case_id


def _restore_historical_store(case_id: str, store: dict[str, Any], case_dir: Path) -> None:
    """Rehydrate archived input state after an API server restart."""
    archive_path = case_dir / "raw" / "historical_replay.json"
    if store.get("historic") or not archive_path.exists():
        return
    archived = json.loads(archive_path.read_text())
    samples = archived["forcing_samples"]
    for sample in samples:
        if "time_s" not in sample:
            sample["time_s"] = datetime.fromisoformat(sample["ts"].replace("Z", "+00:00")).timestamp()
    sources = archived["sources"]
    store.update({
        "case_dir": case_dir,
        "provenance_sar": sources["sar"]["type"],
        "provenance_ais": sources["ais"]["type"],
        "provenance_forcing": sources["forcing"]["type"],
        "source_metadata": sources,
        "forcing": sampled_forcing(samples),
        "historic": True,
    })


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/live/incidents")
def live_incidents(refresh: bool = False):
    """On-demand refresh of the public NOAA IncidentNews incident catalogue."""
    try:
        return fetch_noaa_incidents(force_refresh=refresh)
    except Exception as e:
        raise HTTPException(502, "Could not refresh NOAA IncidentNews right now; the bundled historical snapshot is still available.") from e


@app.get("/api/v1/live/conditions")
def live_conditions(lat: float, lon: float):
    """Current model context for an entered coordinate; not historical forcing."""
    try:
        return fetch_live_conditions(lat, lon)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, "Could not load current marine/weather model context for this location.") from e


@app.get("/api/v1/live/sentinel1")
def live_sentinel1(lat: float, lon: float, start_date: str, end_date: str):
    """Search the Copernicus Data Space catalogue for Sentinel-1 products."""
    try:
        return search_sentinel1(lat, lon, start_date, end_date)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, "Could not search the Copernicus Sentinel-1 catalogue right now.") from e


@app.get("/api/v1/cases")
def list_cases():
    """For the case-input dropdown: every case with raw inputs (`cases/`) or
    a completed bundle (`frontend/public/cases/`)."""
    seen: dict[str, dict] = {}
    if CASES_ROOT.exists():
        for d in CASES_ROOT.iterdir():
            if d.is_dir() and (d / "raw" / "observation_input.json").exists():
                seen[d.name] = {"case_id": d.name, "has_raw_input": True, "has_bundle": False}
    if PUBLIC_CASES_ROOT.exists():
        for d in PUBLIC_CASES_ROOT.iterdir():
            if d.is_dir() and (d / "bundle.json").exists():
                seen.setdefault(d.name, {"case_id": d.name, "has_raw_input": False})
                seen[d.name]["has_bundle"] = True
    return {"cases": list(seen.values())}


@app.post("/api/v1/cases")
async def create_case_from_scene(file: UploadFile = File(...), n_tracks: int = Form(4), gap_rate: float = Form(0.10), loiter_rate: float = Form(0.30)):
    """Real scene upload -> real classical detection (backend/api/geotiff.py).
    provenance.sar = 'provided' (a real uploaded raster); provenance.ais stays
    'synthetic' since real AIS ingest is deferred (§0.1) -- there is no
    ground_truth.json for this path, because there is no real answer to know."""
    if not (file.filename or "").lower().endswith((".tif", ".tiff")):
        raise HTTPException(400, "only .tif/.tiff GeoTIFF uploads are accepted")
    data = await file.read()
    try:
        tiff = geotiff.read_geotiff(data)
        polygon = geotiff.detect_dark_spots(tiff)
    except ValueError as e:
        raise HTTPException(400, f"GeoTIFF detection failed: {e}") from e

    case_id = f"scene-{abs(hash((file.filename, len(data)))) % 100000}"
    case_dir = _case_dir(case_id)
    (case_dir / "raw").mkdir(parents=True, exist_ok=True)
    observed_at = datetime.now(timezone.utc).replace(microsecond=0)
    observation_input = {
        "spill_id": f"spill-{case_id}",
        "image_id": file.filename,
        "observed_at": observed_at.isoformat(),
        "geometry": polygon,
    }
    (case_dir / "raw" / "observation_input.json").write_text(json.dumps(observation_input, indent=2))

    from shapely.geometry import shape as _shape
    centroid = _shape(polygon).centroid
    rng = np.random.default_rng(abs(hash(case_id)) % (2**32))
    from datetime import timedelta
    tracks = generate_regional_traffic(
        rng, centroid.x, centroid.y, observed_at - timedelta(hours=24), observed_at,
        n_tracks, gap_rate, loiter_rate,
    )
    (case_dir / "raw" / "ais_feed.json").write_text(json.dumps(tracks, indent=2))

    store = _case_store(case_id)
    store["case_dir"] = case_dir
    store["provenance_sar"] = "provided"
    return {"case_id": case_id, "n_tracks": len(tracks), "detected_area_hint_px": None}


@app.post("/api/v1/cases/historical")
async def create_historical_case(file: UploadFile = File(...)):
    """Import a replay package built from archived case inputs.

    Required JSON keys: spill_id, image_id, observed_at, geometry (GeoJSON
    Polygon), ais_tracks, forcing_samples, and sources. AIS fixes use
    {ts,lon,lat,sog,cog,heading}; forcing samples use {ts,lon,lat,
    current_u,current_v,wind_u,wind_v}, velocities in m/s, east/north positive.
    No values are fabricated or silently substituted.
    """
    if not (file.filename or "").lower().endswith(".json"):
        raise HTTPException(400, "historical replay package must be a .json file")
    raw_bytes = await file.read()
    if len(raw_bytes) > 25 * 1024 * 1024:
        raise HTTPException(413, "historical replay package exceeds 25 MB")
    try:
        payload = json.loads(raw_bytes)
        required = ("spill_id", "image_id", "observed_at", "geometry", "ais_tracks", "forcing_samples", "sources")
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError("missing fields: " + ", ".join(missing))
        if not payload["ais_tracks"] or not payload["forcing_samples"]:
            raise ValueError("include archived AIS tracks and archived forcing samples")
        from shapely.geometry import shape as _shape
        polygon = _shape(payload["geometry"])
        if polygon.geom_type != "Polygon" or polygon.is_empty or not polygon.is_valid:
            raise ValueError("geometry must be a valid GeoJSON Polygon")
        observed_at = datetime.fromisoformat(payload["observed_at"].replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone (use UTC)")
        if not isinstance(payload["sources"], dict) or not isinstance(payload["ais_tracks"], list) or not isinstance(payload["forcing_samples"], list):
            raise ValueError("sources, ais_tracks, and forcing_samples must be JSON objects/lists")
        tracks = payload["ais_tracks"]
        if len(tracks) > 1000:
            raise ValueError("case contains more than 1,000 AIS tracks; subset to the scene and time window")
        if len(samples := payload["forcing_samples"]) > 10000:
            raise ValueError("case contains more than 10,000 forcing samples; subset to the scene and time window")
        if sum(len(t.get("fixes", [])) for t in tracks) > 100000:
            raise ValueError("case contains more than 100,000 AIS fixes; subset to the scene and time window")
        for ti, track in enumerate(tracks):
            if not track.get("track_id") or len(track.get("fixes", [])) < 2:
                raise ValueError(f"AIS track {ti + 1} needs track_id and at least two fixes")
            for fix in track["fixes"]:
                for key in ("ts", "lon", "lat", "sog", "cog", "heading"):
                    if key not in fix:
                        raise ValueError(f"AIS fix missing {key}")
                fix_time = datetime.fromisoformat(fix["ts"].replace("Z", "+00:00"))
                if fix_time.tzinfo is None:
                    raise ValueError(f"AIS track {ti + 1} timestamps must include timezone")
                for key in ("lon", "lat", "sog", "cog", "heading"):
                    value = float(fix[key])
                    if not math.isfinite(value):
                        raise ValueError(f"AIS track {ti + 1} has a non-finite {key}")
                if not (-180 <= float(fix["lon"]) <= 180 and -90 <= float(fix["lat"]) <= 90):
                    raise ValueError(f"AIS track {ti + 1} has coordinates outside WGS84 bounds")
        for si, sample in enumerate(samples):
            for key in ("ts", "lon", "lat", "current_u", "current_v", "wind_u", "wind_v"):
                if key not in sample:
                    raise ValueError(f"forcing sample {si + 1} missing {key}")
            dt = datetime.fromisoformat(sample["ts"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError(f"forcing sample {si + 1} timestamp must include timezone")
            sample["time_s"] = dt.timestamp()
            for key in ("lon", "lat", "current_u", "current_v", "wind_u", "wind_v"):
                value = float(sample[key])
                if not math.isfinite(value):
                    raise ValueError(f"forcing sample {si + 1} has a non-finite {key}")
            if not (-180 <= float(sample["lon"]) <= 180 and -90 <= float(sample["lat"]) <= 90):
                raise ValueError(f"forcing sample {si + 1} has coordinates outside WGS84 bounds")
        for source_key in ("sar", "ais", "forcing"):
            source = payload["sources"].get(source_key)
            if not isinstance(source, dict) or not source.get("name") or not source.get("url"):
                raise ValueError(f"sources.{source_key} needs a dataset name and source URL")
            if "example.org" in source["url"] or not str(source["url"]).startswith(("https://", "http://")):
                raise ValueError(f"sources.{source_key}.url must be the actual archive citation, not a template URL")
            if source.get("type") not in ("real", "provided"):
                raise ValueError(f"sources.{source_key}.type must be 'real' or 'provided'")
        ais_source = payload["sources"]["ais"]
        ais_name = str(ais_source.get("name", "")).casefold()
        track_source = "synthetic" if "synthetic" in ais_name else ais_source["type"]
        for track in tracks:
            track["source"] = track_source
    except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
        raise HTTPException(400, f"invalid historical replay package: {e}") from e

    case_id = f"historic-{abs(hash((payload['spill_id'], payload['observed_at']))) % 1000000:06d}"
    case_dir = _case_dir(case_id)
    (case_dir / "raw").mkdir(parents=True, exist_ok=True)
    (case_dir / "raw" / "historical_replay.json").write_text(json.dumps(payload, indent=2))
    observation_input = {
        "spill_id": str(payload["spill_id"]),
        "image_id": str(payload["image_id"]),
        "observed_at": observed_at.isoformat(),
        "geometry": payload["geometry"],
    }
    (case_dir / "raw" / "observation_input.json").write_text(json.dumps(observation_input, indent=2))
    (case_dir / "raw" / "ais_feed.json").write_text(json.dumps(tracks, indent=2))
    store = _case_store(case_id)
    store.update({
        "case_dir": case_dir,
        "provenance_sar": payload["sources"]["sar"]["type"],
        "provenance_ais": payload["sources"]["ais"]["type"],
        "provenance_forcing": payload["sources"]["forcing"]["type"],
        "source_metadata": payload["sources"],
        "forcing": sampled_forcing(samples),
        "historic": True,
    })
    return {"case_id": case_id, "n_tracks": len(tracks), "n_forcing_samples": len(samples), "sources": payload["sources"]}


@app.post("/api/v1/cases/synthetic")
def create_synthetic_case(
    lon: float | None = None,
    lat: float | None = None,
    release_time: str | None = None,
    duration_h: float = 20.0,
    n_distractors: int = 4,
    gap_rate: float = 0.10,
    loiter_rate: float = 0.30,
    seed: int = 0,
):
    """Section D's "generate a fresh scenario live" form -> real synth.make_case."""
    case_id = f"live-{seed}-{int(datetime.now().timestamp())}"
    rt = datetime.fromisoformat(release_time) if release_time else None
    result = make_case(
        case_id=case_id, lon=lon, lat=lat, release_time=rt, duration_h=duration_h,
        n_distractors=n_distractors, gap_rate=gap_rate, loiter_rate=loiter_rate,
        seed=seed, out=_case_dir(case_id),
    )
    store = _case_store(case_id)
    store["case_dir"] = _case_dir(case_id)
    store["provenance_sar"] = "synthetic"
    store["ground_truth"] = {  # kept ONLY for the UI to label this as a judge-made scenario; never read by any stage function
        "true_mmsi": result.true_mmsi, "release_lon": result.release_lon, "release_lat": result.release_lat,
    }
    return {"case_id": case_id, "release_lon": result.release_lon, "release_lat": result.release_lat, "release_time": result.release_time, "n_tracks": result.n_tracks}


@app.post("/api/v1/cases/{case_id}/detect")
def detect(case_id: str):
    store = _case_store(case_id)
    case_dir = store.get("case_dir", _case_dir(case_id))
    _restore_historical_store(case_id, store, case_dir)
    if not (case_dir / "raw" / "observation_input.json").exists():
        raise HTTPException(404, f"no raw input for case {case_id!r} -- create it first via POST /api/v1/cases or /api/v1/cases/synthetic")
    observation = load_observation(case_dir)
    provenance = {"sar": store.get("provenance_sar", "synthetic"), "forcing": store.get("provenance_forcing", "synthetic"), "ais": store.get("provenance_ais", "synthetic")}
    observation["provenance"] = provenance
    observation["source_metadata"] = store.get("source_metadata")
    store["case_dir"] = case_dir
    store["observation"] = observation
    store["provenance"] = provenance
    return observation


@app.post("/api/v1/cases/{case_id}/hindcast")
def hindcast(case_id: str, ensemble: int = 30, particles: int = 500, seed: int = 0):
    store = _case_store(case_id)
    _restore_historical_store(case_id, store, store.get("case_dir", _case_dir(case_id)))
    observation = store.get("observation")
    if observation is None:
        raise HTTPException(409, "run /detect first for this case")
    forcing = store.get("forcing") or uniform_forcing()

    def work(progress_cb):
        origin = run_hindcast(observation, forcing, ensemble=ensemble, particles=particles, seed=seed, progress_cb=progress_cb)
        origin_cloud = origin.pop("_origin_cloud")
        raster_path, bounds = save_probability_grid(origin_cloud, _out_dir(case_id))
        origin["probability_raster_path"] = raster_path
        store["origin"] = origin
        store["origin_cloud"] = origin_cloud
        store["opm_bounds"] = bounds
        store["forcing"] = forcing
        return origin

    job_id = jobs.create_job(work)
    return JSONResponse(status_code=202, content={"job_id": job_id})


@app.post("/api/v1/cases/{case_id}/traffic")
def traffic(case_id: str, buffer_km: float = 25.0, max_speed_kn: float = 25.0, min_fixes: int = 5):
    store = _case_store(case_id)
    origin = store.get("origin")
    if origin is None:
        raise HTTPException(409, "run /hindcast first for this case")
    case_dir = store["case_dir"]
    raw_tracks = json.loads((case_dir / "raw" / "ais_feed.json").read_text())
    candidates = reconstruct(raw_tracks, origin, buffer_km=buffer_km, max_speed_kn=max_speed_kn, min_fixes=min_fixes)
    store["tracks"] = candidates
    return {"tracks": candidates, "n_filtered_out": len(raw_tracks) - len(candidates)}


@app.post("/api/v1/cases/{case_id}/simulate")
def simulate(case_id: str, release_interval_min: float = 12.0, particles_per_release: int = 100, seed: int = 0):
    store = _case_store(case_id)
    candidates = store.get("tracks")
    origin = store.get("origin")
    observation = store.get("observation")
    forcing = store.get("forcing")
    if not candidates or origin is None or observation is None:
        raise HTTPException(409, "run /detect, /hindcast, and /traffic first for this case")
    if len(candidates) == 0:
        # honest empty state, not a fabricated candidate
        store["candidates"] = []
        return JSONResponse(status_code=200, content={"candidates": [], "empty_reason": "No candidates met the reachability filter"})

    window_start = datetime.fromisoformat(origin["window_start"])
    window_end = datetime.fromisoformat(origin["window_end"])
    observed_at = datetime.fromisoformat(observation["observed_at"])
    weights_cfg = load_weights(WEIGHTS_PATH)
    origin_cloud = store["origin_cloud"]

    def work(progress_cb):
        m6_results = run_counterfactual(
            candidates, window_start, window_end, observed_at, observation["geometry"], forcing,
            release_interval_min=release_interval_min, particles_per_release=particles_per_release,
            seed=seed, progress_cb=progress_cb,
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
        store["candidates"] = scored
        _write_bundle(case_id, store, weights_cfg, release_interval_min, particles_per_release)
        return scored

    job_id = jobs.create_job(work)
    return JSONResponse(status_code=202, content={"job_id": job_id})


def _write_bundle(case_id: str, store: dict, weights_cfg: dict, release_interval_min: float, particles_per_release: int) -> None:
    bundle = {
        "case_id": case_id,
        "provenance": store.get("provenance", {"sar": "synthetic", "forcing": "synthetic", "ais": "synthetic"}),
        "source_metadata": store.get("source_metadata"),
        "observation": {**store["observation"], "provenance": store.get("provenance", {"sar": "synthetic", "forcing": "synthetic", "ais": "synthetic"})},
        "origin": {k: v for k, v in store["origin"].items() if not k.startswith("_")},
        "tracks": store["tracks"],
        "candidates": store["candidates"],
        "assets": {
            "sar_png": "assets/sar_not_rendered.png",
            "opm_png": "assets/opm_not_rendered.png",
            "opm_bounds": store.get("opm_bounds", [0, 0, 0, 0]),
        },
        "config_snapshot": {
            "weights": weights_cfg["weights"],
            "drift": {
                "ensemble_size": store["origin"]["ensemble_size"],
                "particles_per_release": particles_per_release,
                "windage_range": [0.02, 0.04],
                "footprint_method": "alpha_shape",
                "drift_compat_norm": "D = 0.6*hit_rate + 0.4*iou",
            },
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    CaseBundle.model_validate(bundle)  # never write a bundle that doesn't conform
    out_dir = _out_dir(case_id)
    (out_dir / "bundle.json").write_text(json.dumps(bundle, indent=2, default=str))
    store["bundle"] = bundle


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "unknown job_id")
    return jobs.job_to_dict(job)


@app.get("/api/v1/cases/{case_id}")
def get_case(case_id: str):
    bundle_path = _out_dir(case_id) / "bundle.json"
    if bundle_path.exists():
        return json.loads(bundle_path.read_text())
    store = _CASES.get(case_id)
    if store and "bundle" in store:
        return store["bundle"]
    raise HTTPException(404, f"case {case_id!r} has no completed bundle yet -- run all stages first")


@app.get("/api/v1/cases/{case_id}/export.geojson")
def export_geojson(case_id: str):
    bundle_path = _out_dir(case_id) / "bundle.json"
    if not bundle_path.exists():
        raise HTTPException(404, "bundle not ready -- run /simulate first")
    bundle = json.loads(bundle_path.read_text())
    features = [{"type": "Feature", "geometry": bundle["observation"]["geometry"], "properties": {"kind": "observed_slick"}}]
    for c in bundle["candidates"]:
        if c["best_release"]:
            features.append({"type": "Feature", "geometry": c["best_release"]["simulated_geometry"], "properties": {"kind": "simulated_slick", "track_id": c["track_id"], "association": c["association"]}})
    return {"type": "FeatureCollection", "features": features}


@app.get("/api/v1/cases/{case_id}/report.pdf")
def report_pdf(case_id: str):
    bundle_path = _out_dir(case_id) / "bundle.json"
    if not bundle_path.exists():
        raise HTTPException(404, "bundle not ready -- run /simulate first")
    bundle = json.loads(bundle_path.read_text())
    pdf_bytes = build_report_pdf(bundle)
    return Response(content=pdf_bytes, media_type="application/pdf")


@app.get("/api/v1/cases/{case_id}/assets/{name}")
def get_asset(case_id: str, name: str):
    path = _out_dir(case_id) / "assets" / name
    if not path.exists():
        raise HTTPException(404, f"asset {name!r} not found for case {case_id!r}")
    return FileResponse(str(path))
