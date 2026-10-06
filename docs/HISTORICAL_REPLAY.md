# Historical replay import

This import runs the existing investigation stages on one archived case. It does not automatically download data or invent missing records. The JSON example in `frontend/public/historical_case_template.json` is a **format example only**; its track and forcing values are placeholders and must be replaced before import.

## Input package

Upload a JSON file with these top-level fields:

- `spill_id`, `image_id`, `observed_at`: source case/image identifiers and acquisition time. `observed_at` must be ISO 8601 with timezone, preferably UTC (`Z`).
- `geometry`: a valid GeoJSON `Polygon` in WGS84 longitude/latitude. It should be the interpreted slick footprint for the archived observation; if manually digitized, mark SAR `type` as `provided`.
- `sources`: `sar`, `ais`, and `forcing` objects, each with `type` (`real` or `provided`), `name`, and a resolvable citation/URL.
- `ais_tracks`: array of tracks with `track_id`, optional `mmsi` / `vessel_type`, and `fixes`. Each fix has `ts`, `lon`, `lat`, `sog` (knots), `cog`, and `heading` (degrees). Use archived records only and ensure the source allows this use.
- `forcing_samples`: time/position samples with `ts`, `lon`, `lat`, `current_u`, `current_v`, `wind_u`, and `wind_v`. Current and wind are in m/s, east/north positive. The replay uses nearest archived sample by space and time; it does not interpolate a full grid. Forcing quality is therefore surfaced as medium.

AIS and forcing timestamps should span the observation and the estimated release window. Clip the input to the region and date range before import. The API currently accepts up to 25 MB per case. Every layer's real/provided provenance is persisted into the resulting case/report.

## Public archive references

- NOAA IncidentNews publishes a machine-readable CSV of selected spill incidents. NOAA notes that its reported open date is the date NOAA was notified, which can differ from the spill date; confirm the event date/location against incident reports before using it as ground truth: <https://incidentnews.noaa.gov/raw/index>
- NOAA's historical incident catalog contains oil/chemical spill reports and images, mainly U.S. cases: <https://www.fisheries.noaa.gov/inport/item/40830>
- Copernicus Marine's Global Ocean Physics Reanalysis (GLORYS12V1) covers 1993 onward and includes daily/monthly ocean currents: <https://data.marine.copernicus.eu/product/GLOBAL_MULTIYEAR_PHY_001_030/description>
- Historical AIS must come from an archive that authorizes access and use. This application does not provide or retrieve vessel tracks itself.

NOAA incident metadata can establish event context, but it is not satellite slick geometry, an AIS trajectory, or proof that any vessel caused a spill. Keep those evidence types separate in the review.
