"""On-demand public data adapters used by the live-data workspace.

NOAA IncidentNews is a live-updatable event catalogue, not a trajectory feed.
Open-Meteo current marine/weather endpoints provide model context for present
conditions only; they must not be substituted for archived forcing in an old
case replay. AIS remains a separately licensed/provider-supplied input.
"""

from __future__ import annotations

import csv
import io
import json
import math
import threading
from datetime import datetime, timezone
from time import monotonic
from urllib.parse import urlencode
from urllib.request import Request, urlopen


NOAA_INCIDENTS_URL = "https://incidentnews.noaa.gov/raw/incidents.csv"
OPEN_METEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
OPEN_METEO_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
_INCIDENT_TTL_SECONDS = 15 * 60
_incident_cache: dict | None = None
_incident_cached_at = 0.0
_cache_lock = threading.Lock()
CDSE_ODATA_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"


def _read_url(url: str, accept: str = "application/json") -> bytes:
    request = Request(url, headers={"User-Agent": "SamudraSakshi/1.0 (research dashboard)", "Accept": accept})
    with urlopen(request, timeout=25) as response:
        return response.read()


def fetch_noaa_incidents(force_refresh: bool = False) -> dict:
    """Fetch NOAA's current public CSV snapshot and cache it for 15 minutes."""
    global _incident_cache, _incident_cached_at
    with _cache_lock:
        if not force_refresh and _incident_cache is not None and monotonic() - _incident_cached_at < _INCIDENT_TTL_SECONDS:
            return _incident_cache
    raw = _read_url(NOAA_INCIDENTS_URL, "text/csv")
    records = []
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))
    for row in reader:
        try:
            lat = float(row["lat"]) if row.get("lat") else None
            lon = float(row["lon"]) if row.get("lon") else None
        except (TypeError, ValueError):
            lat = lon = None
        records.append({
            "id": str(row.get("id", "")).strip(),
            "date": str(row.get("open_date", "")).strip(),
            "name": str(row.get("name", "")).strip(),
            "location": str(row.get("location", "")).strip(),
            "lat": lat,
            "lon": lon,
            "threat": str(row.get("threat", "")).strip(),
            "commodity": str(row.get("commodity", "")).strip(),
            "releaseGallons": str(row.get("max_ptl_release_gallons", "")).strip(),
            "description": str(row.get("description", "")).replace("\x0b", " ").strip(),
            "tags": str(row.get("tags", "")).strip(),
        })
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = {
        "records": records,
        "record_count": len(records),
        "fetched_at_utc": fetched_at,
        "source": {"name": "NOAA IncidentNews raw incident CSV", "url": NOAA_INCIDENTS_URL, "type": "live_public_catalog"},
    }
    with _cache_lock:
        _incident_cache = result
        _incident_cached_at = monotonic()
    return result


def _get_current(payload: dict, key: str) -> float | None:
    value = (payload.get("current") or {}).get(key)
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def fetch_live_conditions(latitude: float, longitude: float) -> dict:
    """Fetch modeled present conditions and convert wind/current to east/north m/s."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("latitude/longitude must be valid WGS84 coordinates")
    marine_query = urlencode({
        "latitude": latitude, "longitude": longitude,
        "current": "ocean_current_velocity,ocean_current_direction",
        "wind_speed_unit": "ms", "timezone": "UTC",
    })
    weather_query = urlencode({
        "latitude": latitude, "longitude": longitude,
        "current": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "ms", "timezone": "UTC",
    })
    marine = json.loads(_read_url(f"{OPEN_METEO_MARINE_URL}?{marine_query}"))
    weather = json.loads(_read_url(f"{OPEN_METEO_WEATHER_URL}?{weather_query}"))
    current_speed = _get_current(marine, "ocean_current_velocity")
    current_dir = _get_current(marine, "ocean_current_direction")
    wind_speed = _get_current(weather, "wind_speed_10m")
    wind_from = _get_current(weather, "wind_direction_10m")
    if current_speed is None or current_dir is None or wind_speed is None or wind_from is None:
        raise ValueError("one or more live model fields are unavailable for this location")
    cr = math.radians(current_dir)
    wr = math.radians(wind_from)
    return {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_time_utc": (marine.get("current") or {}).get("time") or (weather.get("current") or {}).get("time"),
        "requested_location": {"lat": latitude, "lon": longitude},
        "grid_location": {"lat": marine.get("latitude"), "lon": marine.get("longitude")},
        "classification": "current_model_estimate",
        "forcing": {
            "current_speed_m_s": current_speed,
            "current_direction_to_deg": current_dir,
            "current_u_m_s": current_speed * math.sin(cr),
            "current_v_m_s": current_speed * math.cos(cr),
            "wind_speed_m_s": wind_speed,
            "wind_direction_from_deg": wind_from,
            "wind_u_m_s": -wind_speed * math.sin(wr),
            "wind_v_m_s": -wind_speed * math.cos(wr),
        },
        "sources": [
            {"name": "Open-Meteo Marine API", "url": "https://open-meteo.com/en/docs/marine-weather-api"},
            {"name": "Open-Meteo Weather API", "url": "https://open-meteo.com/en/docs"},
            {"name": "DWD model attribution", "url": "https://www.dwd.de/EN/Home/home_node.html"},
        ],
        "quality_note": "Modelled present conditions, not an in-situ observation. Coastal grid-cell accuracy is limited. Do not use this current snapshot for a historical spill replay.",
    }


def search_sentinel1(latitude: float, longitude: float, start_date: str, end_date: str) -> dict:
    """Find Sentinel-1 scene metadata covering a coordinate and sensing-date window."""
    from datetime import date, timedelta

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("latitude/longitude must be valid WGS84 coordinates")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as e:
        raise ValueError("scene-search dates must use YYYY-MM-DD") from e
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    if (end - start).days > 14:
        raise ValueError("scene-search window may not exceed 15 days")
    point = f"POINT({longitude:.6f} {latitude:.6f})"
    filter_expr = (
        "Collection/Name eq 'SENTINEL-1' and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{point}') and "
        f"ContentDate/Start ge {start.isoformat()}T00:00:00.000Z and "
        f"ContentDate/Start lt {(end + timedelta(days=1)).isoformat()}T00:00:00.000Z"
    )
    query = urlencode({"$filter": filter_expr, "$top": "20", "$orderby": "ContentDate/Start desc"})
    url = f"{CDSE_ODATA_URL}?{query}"
    payload = json.loads(_read_url(url))
    products = []
    for item in payload.get("value", []):
        content_date = item.get("ContentDate") or {}
        products.append({
            "id": item.get("Id"),
            "name": item.get("Name"),
            "start": content_date.get("Start"),
            "end": content_date.get("End"),
            "online": item.get("Online"),
            "metadata_url": f"{CDSE_ODATA_URL}({item.get('Id')})" if item.get("Id") else None,
        })
    return {
        "products": products,
        "count": len(products),
        "query": {"lat": latitude, "lon": longitude, "start_date": start_date, "end_date": end_date},
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"name": "Copernicus Data Space Sentinel-1 OData catalogue", "url": "https://documentation.dataspace.copernicus.eu/APIs/OData.html"},
        "note": "Live catalogue metadata only. Download and process the selected product before treating it as an observed slick; a catalogue match is not an oil-spill detection.",
    }
