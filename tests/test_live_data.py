import json
from urllib.parse import parse_qs, urlparse

import pytest

from backend.api import live_data


def test_noaa_csv_adapter_maps_live_incident_schema(monkeypatch):
    raw = (
        "id,open_date,name,location,lat,lon,threat,commodity,max_ptl_release_gallons,description,tags\n"
        '7,2026-09-28,"Test spill","Bay, CA",37.1,-122.2,Oil,Diesel,50,"A test record",Grounding\n'
    ).encode()
    monkeypatch.setattr(live_data, "_read_url", lambda *args, **kwargs: raw)
    result = live_data.fetch_noaa_incidents(force_refresh=True)
    assert result["record_count"] == 1
    assert result["records"][0]["lat"] == 37.1
    assert result["records"][0]["releaseGallons"] == "50"
    assert result["source"]["type"] == "live_public_catalog"


def test_live_conditions_convert_direction_to_east_north(monkeypatch):
    marine = {"latitude": 25.0, "longitude": -80.0, "current": {
        "time": "2026-09-29T18:00", "ocean_current_velocity": 2.0, "ocean_current_direction": 90.0,
    }}
    weather = {"current": {
        "time": "2026-09-29T18:00", "wind_speed_10m": 4.0, "wind_direction_10m": 0.0,
    }}

    def mock_read(url, *args, **kwargs):
        return json.dumps(marine if "marine-api" in url else weather).encode()

    monkeypatch.setattr(live_data, "_read_url", mock_read)
    result = live_data.fetch_live_conditions(25.0, -80.0)
    assert abs(result["forcing"]["current_u_m_s"] - 2.0) < 1e-9
    assert abs(result["forcing"]["current_v_m_s"]) < 1e-9
    assert abs(result["forcing"]["wind_v_m_s"] + 4.0) < 1e-9
    assert result["classification"] == "current_model_estimate"


def test_sentinel1_search_builds_spatial_and_time_query(monkeypatch):
    captured = {}
    payload = {"value": [{
        "Id": "scene-1", "Name": "S1_TEST_GRD", "Online": True,
        "ContentDate": {"Start": "2026-09-28T10:00:00Z", "End": "2026-09-28T10:00:20Z"},
    }]}

    def mock_read(url, *args, **kwargs):
        captured["url"] = url
        return json.dumps(payload).encode()

    monkeypatch.setattr(live_data, "_read_url", mock_read)
    result = live_data.search_sentinel1(13.08, 80.27, "2026-09-28", "2026-09-29")
    query = parse_qs(urlparse(captured["url"]).query)
    assert "POINT(80.270000 13.080000)" in query["$filter"][0]
    assert "2026-09-28T00:00:00.000Z" in query["$filter"][0]
    assert result["products"][0]["name"] == "S1_TEST_GRD"
    assert result["products"][0]["metadata_url"].endswith("(scene-1)")


def test_sentinel1_search_rejects_invalid_ranges():
    with pytest.raises(ValueError, match="WGS84"):
        live_data.search_sentinel1(91, 0, "2026-01-01", "2026-01-02")
    with pytest.raises(ValueError, match="may not exceed"):
        live_data.search_sentinel1(0, 0, "2026-01-01", "2026-01-20")
