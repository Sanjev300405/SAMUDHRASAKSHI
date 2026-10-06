# SAMUDRA SAKSHI

A prototype workflow for reviewing oil-slick observations, tracing possible origins, replaying vessel tracks, comparing drift hypotheses, and exporting a case report. Associations are evidence summaries for human review, not guilt probabilities or legal findings.

## Run the backend

From the repository root, create and activate a Python 3.11+ virtual environment, then install dependencies and start FastAPI:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8000
```

On macOS/Linux, activate with `source .venv/bin/activate`. On Command Prompt, use `.venv\Scripts\activate.bat`.

## Run the frontend

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open the Vite URL (normally http://localhost:5173). The backend must be running for case creation and exports. With the backend unavailable, the bundled demo remains available in offline mode.

## Data modes

- **Historical incident catalog:** browse the bundled `incidents.csv` snapshot (4,940 records, 1957–2026) and use **Refresh NOAA** to fetch the latest public IncidentNews CSV. See [`docs/INCIDENT_CATALOG.md`](docs/INCIDENT_CATALOG.md).
- **Live scene discovery:** search Copernicus Data Space for Sentinel-1 products by incident coordinates and date. The app shows product metadata; the selected raster still needs to be retrieved and processed.
- **Current marine context:** fetch current modelled ocean current and 10 m wind at an incident coordinate through Open-Meteo. This is present-day context only and is never inserted into a historical replay.
- **Historical replay:** import an archived case package. Format and source requirements are in [`docs/HISTORICAL_REPLAY.md`](docs/HISTORICAL_REPLAY.md). It consumes the supplied SAR-derived polygon, AIS fixes, and time-varying historical forcing samples; the app does not fetch these providers automatically.
- **SAR GeoTIFF:** upload a supported raster for classical dark-spot detection. AIS and ocean forcing remain synthetic for this route.
- **Synthetic demo:** generate a reproducible synthetic scenario for workflow testing.

The live adapters are useful for source discovery and current conditions. They do not create a complete historical attribution case. There is no unrestricted free global AIS feed in this build; use an authorised AIS archive/provider or clearly labelled synthetic demo tracks. For historical forcing, import samples matched to the scene timestamp rather than using today's conditions. All candidate scores are investigative associations, not proof of responsibility. See [`docs/LIVE_DATA.md`](docs/LIVE_DATA.md).

### Complete-workflow demonstration replay

`examples/DWH_2010_Simulation_Demo_SYNTHETIC_AIS.json` is a runnable workflow demonstration. Its wind/current samples are from the supplied historical forcing package, but its SAR outline is approximate and its AIS tracks are synthetic. Upload this JSON through **Historical replay → Choose replay package**, then run **Detect → Hindcast → Analyse Traffic → Run Simulation**. The resulting candidate ranking is for software demonstration only; it is not evidence about any real vessel. Use archived AIS with the matching dates and area for historical attribution.

## Tests / build

```bash
python -m pytest
cd frontend
npm run build
```
