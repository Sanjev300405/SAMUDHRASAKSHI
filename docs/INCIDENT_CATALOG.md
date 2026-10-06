# Historical incident catalog

The web dashboard includes a searchable incident catalog generated from the supplied `incidents.csv`. It contains 4,940 records dated 1957-03-29 through 2026-09-28. Use **Refresh NOAA** to fetch the current public CSV snapshot when the backend has internet access. NOAA's catalogue covers selected incidents where its Office of Response and Restoration provided support; it is not a worldwide census. NOAA explains that `open_date` is usually its notification date, coordinates may be approximate, and some pre-1985 dates come from third-party sources. See [NOAA's raw data notes](https://incidentnews.noaa.gov/raw/index).

## What it can and cannot do

The CSV contains incident metadata and coordinates. It does not include SAR slick polygons or imagery, historical AIS fixes, or time-matched ocean current and wind observations. Selecting a catalog record therefore opens an incident information card only; it does not run slick detection, source-origin hindcasting, vessel ranking, or attribution. For a selected record, the dashboard can search Copernicus Data Space for Sentinel-1 scene metadata near the coordinate and date. A matching scene still needs to be retrieved and processed. Sentinel-1A launched in 2014, so pre-2014 events require an older SAR archive.

To run the full analysis, use **Historical replay** and import a complete replay package that includes an archived slick geometry, AIS tracks with timestamps, current/wind samples for the matching date and region, and source/provenance references. The app does not fabricate missing layers.

The catalog tab is independent of the cached synthetic demo. The map pipeline remains labeled as a sample scenario when its inputs are synthetic. A current marine/weather lookup is only present-day context and is not used for a historical event's hindcast.
