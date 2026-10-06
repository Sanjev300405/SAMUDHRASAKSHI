from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
from fastapi.testclient import TestClient

from backend.adapters.forcing import sampled_forcing
from backend.api import main


def _historical_payload() -> dict:
    return {
        "spill_id": "archive-test-01",
        "image_id": "sar-scene-01",
        "observed_at": "2010-04-21T12:00:00Z",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-88.6, 28.5], [-88.3, 28.5], [-88.3, 28.8], [-88.6, 28.8], [-88.6, 28.5]]],
        },
        "sources": {
            "sar": {"type": "provided", "name": "Digitized archive footprint", "url": "https://response.restoration.noaa.gov/"},
            "ais": {"type": "real", "name": "Authorized archive AIS", "url": "https://www.noaa.gov/"},
            "forcing": {"type": "real", "name": "Archived ocean and wind samples", "url": "https://data.marine.copernicus.eu/"},
        },
        "ais_tracks": [{
            "track_id": "archive-track-1", "mmsi": "123456789", "vessel_type": "cargo",
            "fixes": [
                {"ts": "2010-04-20T12:00:00Z", "lon": -88.45, "lat": 28.60, "sog": 8.0, "cog": 90, "heading": 90},
                {"ts": "2010-04-21T00:00:00Z", "lon": -88.40, "lat": 28.61, "sog": 8.0, "cog": 90, "heading": 90},
            ],
        }],
        "forcing_samples": [
            {"ts": "2010-04-20T12:00:00Z", "lon": -88.45, "lat": 28.60, "current_u": 0.1, "current_v": 0.0, "wind_u": 2.0, "wind_v": 1.0},
            {"ts": "2010-04-21T12:00:00Z", "lon": -88.45, "lat": 28.60, "current_u": 0.2, "current_v": 0.0, "wind_u": 3.0, "wind_v": 1.0},
        ],
    }


def test_sampled_forcing_uses_nearest_historical_time_and_location():
    samples = [
        {"time_s": 0, "lon": 0, "lat": 0, "current_u": 1, "current_v": 2, "wind_u": 3, "wind_v": 4},
        {"time_s": 3600, "lon": 1, "lat": 0, "current_u": 5, "current_v": 6, "wind_u": 7, "wind_v": 8},
    ]
    forcing = sampled_forcing(samples)
    u0, v0 = forcing.current(np.array([0.001]), np.array([0.0]), 100)
    u1, v1 = forcing.current(np.array([0.999]), np.array([0.0]), 3500)
    assert (u0[0], v0[0], u1[0], v1[0]) == (1, 2, 5, 6)
    assert forcing.quality == "medium"
    assert forcing.uniform is False


def test_historical_import_marks_provenance_and_survives_api_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "CASES_ROOT", tmp_path / "cases")
    monkeypatch.setattr(main, "PUBLIC_CASES_ROOT", tmp_path / "public-cases")
    main._CASES.clear()
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/cases/historical",
            files={"file": ("archive.json", json.dumps(_historical_payload()), "application/json")},
        )
        assert response.status_code == 200, response.text
        case_id = response.json()["case_id"]

        detection = client.post(f"/api/v1/cases/{case_id}/detect")
        assert detection.status_code == 200, detection.text
        observation = detection.json()
        assert observation["observed_at"].startswith("2010-04-21")
        assert observation["provenance"] == {"sar": "provided", "ais": "real", "forcing": "real"}
        assert observation["source_metadata"]["ais"]["name"] == "Authorized archive AIS"

        # A restarted process must be able to restore the source metadata and
        # sampled forcing from the saved case package rather than defaulting to synthetic.
        main._CASES.clear()
        detection_after_restart = client.post(f"/api/v1/cases/{case_id}/detect")
        assert detection_after_restart.status_code == 200
        assert detection_after_restart.json()["provenance"]["forcing"] == "real"
        restored = main._CASES[case_id]["forcing"]
        assert restored.uniform is False
        assert restored.quality == "medium"
