// Section D. Three real ways to give the app an input: pick an existing
// case, upload a real GeoTIFF (runs real detection), or generate a fresh
// synthetic scenario live via synth/make_case.py's own flags.
import { useEffect, useState } from 'react';
import * as api from '../lib/api';

interface Props {
  open: boolean;
  onClose: () => void;
  onSelectCase: (caseId: string) => void;
  disabled: boolean; // true in offline mode -- no network calls possible
}

type IncidentRecord = api.LiveIncidentRecord;

export default function CaseInputPanel({ open, onClose, onSelectCase, disabled }: Props) {
  const [cases, setCases] = useState<api.CaseListing[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [lon, setLon] = useState('');
  const [lat, setLat] = useState('');
  const [releaseTime, setReleaseTime] = useState('');
  const [nDistractors, setNDistractors] = useState(4);
  const [gapRate, setGapRate] = useState(0.10);
  const [seed, setSeed] = useState(1);
  const [inputTab, setInputTab] = useState<'incidents' | 'historical' | 'scene' | 'synthetic'>('incidents');
  const [incidentRecords, setIncidentRecords] = useState<IncidentRecord[]>([]);
  const [incidentQuery, setIncidentQuery] = useState('');
  const [selectedIncident, setSelectedIncident] = useState<IncidentRecord | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogUpdatedAt, setCatalogUpdatedAt] = useState<string | null>(null);
  const [catalogSource, setCatalogSource] = useState('Bundled snapshot');
  const [refreshingIncidents, setRefreshingIncidents] = useState(false);
  const [liveConditions, setLiveConditions] = useState<api.LiveConditions | null>(null);
  const [conditionsBusy, setConditionsBusy] = useState(false);
  const [conditionsError, setConditionsError] = useState<string | null>(null);
  const [sceneStart, setSceneStart] = useState('');
  const [sceneEnd, setSceneEnd] = useState('');
  const [sceneProducts, setSceneProducts] = useState<api.Sentinel1Product[] | null>(null);
  const [sceneBusy, setSceneBusy] = useState(false);
  const [sceneError, setSceneError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || disabled) return;
    api.listCases().then(setCases).catch((e) => setError(String(e)));
  }, [open, disabled]);

  useEffect(() => {
    if (!open || inputTab !== 'incidents' || incidentRecords.length) return;
    fetch('/incidents_catalog.json')
      .then((res) => { if (!res.ok) throw new Error(`Catalog request failed (${res.status})`); return res.json(); })
      .then((data: { records: IncidentRecord[] }) => setIncidentRecords(data.records))
      .catch((e) => setCatalogError(e instanceof Error ? e.message : String(e)));
  }, [open, inputTab, incidentRecords.length]);

  useEffect(() => {
    if (!selectedIncident?.date) return;
    const center = new Date(`${selectedIncident.date}T00:00:00Z`);
    const shift = (days: number) => {
      const date = new Date(center);
      date.setUTCDate(date.getUTCDate() + days);
      return date.toISOString().slice(0, 10);
    };
    setSceneStart(shift(-1)); setSceneEnd(shift(1)); setSceneProducts(null); setSceneError(null);
    setLiveConditions(null); setConditionsError(null);
  }, [selectedIncident?.id]);

  if (!open) return null;

  const normalizedQuery = incidentQuery.trim().toLowerCase();
  const filteredIncidents = incidentRecords.filter((r) => !normalizedQuery ||
    `${r.name} ${r.location} ${r.date} ${r.threat} ${r.description}`.toLowerCase().includes(normalizedQuery)
  ).slice(0, 120);

  const refreshIncidentCatalog = async () => {
    setRefreshingIncidents(true); setCatalogError(null);
    try {
      const data = await api.refreshLiveIncidents();
      setIncidentRecords(data.records);
      setCatalogUpdatedAt(data.fetched_at_utc);
      setCatalogSource('NOAA live refresh');
      setSelectedIncident((selected) => selected ? data.records.find((r) => r.id === selected.id) ?? selected : null);
    } catch (e) {
      setCatalogError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshingIncidents(false);
    }
  };

  const loadLiveConditions = async () => {
    if (!selectedIncident || selectedIncident.lat == null || selectedIncident.lon == null) return;
    setConditionsBusy(true); setConditionsError(null); setLiveConditions(null);
    try {
      setLiveConditions(await api.getLiveConditions(Number(selectedIncident.lat), Number(selectedIncident.lon)));
    } catch (e) {
      setConditionsError(e instanceof Error ? e.message : String(e));
    } finally {
      setConditionsBusy(false);
    }
  };

  const findSentinel1 = async () => {
    if (!selectedIncident || selectedIncident.lat == null || selectedIncident.lon == null) return;
    setSceneBusy(true); setSceneError(null); setSceneProducts(null);
    try {
      const data = await api.searchSentinel1(Number(selectedIncident.lat), Number(selectedIncident.lon), sceneStart, sceneEnd);
      setSceneProducts(data.products);
    } catch (e) {
      setSceneError(e instanceof Error ? e.message : String(e));
    } finally {
      setSceneBusy(false);
    }
  };

  const handleGenerate = async () => {
    setBusy(true); setError(null);
    try {
      const params: api.SyntheticCaseParams = {
        nDistractors, gapRate, seed,
        ...(lon ? { lon: parseFloat(lon) } : {}),
        ...(lat ? { lat: parseFloat(lat) } : {}),
        ...(releaseTime ? { releaseTime } : {}),
      };
      const res = await api.createSyntheticCase(params);
      onSelectCase(res.case_id);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleUpload = async (file: File) => {
    setBusy(true); setError(null);
    try {
      const res = await api.uploadGeoTiff(file);
      onSelectCase(res.case_id);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleHistoricalUpload = async (file: File) => {
    setBusy(true); setError(null);
    try {
      const res = await api.uploadHistoricalCase(file);
      onSelectCase(res.case_id);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="intro-overlay" onClick={onClose}>
      <div className="panel e3 case-input" onClick={(e) => e.stopPropagation()}>
        <div className="case-input__header">
          <div>
            <span className="label">Case workspace</span>
            <h2 className="case-input__title">Choose an investigation</h2>
            <div className="case-input__subtitle">Replay archived observations and environmental records, or open a prototype case.</div>
          </div>
          <button className="case-input__close" onClick={onClose} aria-label="Close">&times;</button>
        </div>

        {disabled && (
          <div className="panel-state panel-state--degraded">Offline mode is active -- case creation needs the live API. Add ?offline=0 or start the server to enable this.</div>
        )}
        {error && <div className="panel-state panel-state--error">{error}</div>}

        <section className="case-input__section">
          <div className="label" style={{ color: 'var(--fg-tertiary)' }}>Existing cases</div>
          {cases.length === 0 ? (
            <div className="panel-state panel-state--empty">No cases found under frontend/public/cases/ or cases/ yet.</div>
          ) : (
            <select
              className="case-input__select"
              disabled={disabled || busy}
              defaultValue=""
              onChange={(e) => { if (e.target.value) { onSelectCase(e.target.value); onClose(); } }}
            >
              <option value="" disabled>Select a case&hellip;</option>
              {cases.map((c) => (
                <option key={c.case_id} value={c.case_id}>{c.case_id}{c.has_bundle ? ' (complete)' : ' (raw only)'}</option>
              ))}
            </select>
          )}
        </section>

        <section className="case-input__section">
          <div className="label" style={{ color: 'var(--fg-tertiary)' }}>Create or import</div>
          <div className="case-input__tabs" role="tablist" aria-label="Case input type">
            <button role="tab" aria-selected={inputTab === 'incidents'} className={inputTab === 'incidents' ? 'is-active' : ''} onClick={() => setInputTab('incidents')}>Incident catalog</button>
            <button role="tab" aria-selected={inputTab === 'historical'} className={inputTab === 'historical' ? 'is-active' : ''} onClick={() => setInputTab('historical')}>Historical replay</button>
            <button role="tab" aria-selected={inputTab === 'scene'} className={inputTab === 'scene' ? 'is-active' : ''} onClick={() => setInputTab('scene')}>SAR GeoTIFF</button>
            <button role="tab" aria-selected={inputTab === 'synthetic'} className={inputTab === 'synthetic' ? 'is-active' : ''} onClick={() => setInputTab('synthetic')}>Synthetic demo</button>
          </div>
          {inputTab === 'incidents' && (
            <div className="case-input__history" role="tabpanel">
              <div className="case-input__history-head"><span className="history-mark">◎</span><div><strong>Historical incident records</strong><span>{incidentRecords.length.toLocaleString()} records · {catalogSource}{catalogUpdatedAt ? ` · refreshed ${new Date(catalogUpdatedAt).toLocaleString()}` : ' · March 1957–September 2026'}</span></div></div>
              <div className="incident-toolbar">
                <input className="incident-search" type="search" value={incidentQuery} onChange={(e) => setIncidentQuery(e.target.value)} placeholder="Search incident, place, date, or description" aria-label="Search historical incidents" />
                <button className="incident-refresh" onClick={refreshIncidentCatalog} disabled={disabled || refreshingIncidents}>{refreshingIncidents ? 'Refreshing…' : '↻ Refresh NOAA'}</button>
              </div>
              {catalogError && <div className="panel-state panel-state--error">Could not load incident catalog: {catalogError}</div>}
              {!incidentRecords.length && !catalogError && <div className="panel-state panel-state--loading">Loading historical records…</div>}
              {incidentRecords.length > 0 && (
                <div className="incident-browser">
                  <div className="incident-list" aria-label="Historical incidents">
                    {filteredIncidents.map((record) => (
                      <button key={record.id} className={`incident-row${selectedIncident?.id === record.id ? ' is-selected' : ''}`} onClick={() => setSelectedIncident(record)}>
                        <span className="incident-row__date">{record.date || 'Date unavailable'} · {record.threat || 'Incident'}</span>
                        <strong>{record.name || 'Unnamed incident'}</strong>
                        <span>{record.location}</span>
                      </button>
                    ))}
                    {filteredIncidents.length === 0 && <div className="panel-state panel-state--empty">No matching incidents.</div>}
                    {filteredIncidents.length === 120 && <div className="incident-list__more">Showing first 120 matches. Refine your search to narrow results.</div>}
                  </div>
                  {selectedIncident && (
                    <article className="incident-detail">
                      <div className="label">Incident record · {selectedIncident.id}</div>
                      <h3>{selectedIncident.name}</h3>
                      <div className="incident-detail__meta">NOAA record date: {selectedIncident.date} · {selectedIncident.location}</div>
                      {(selectedIncident.lat != null || selectedIncident.lon != null) && <div className="incident-detail__meta">Coordinates: {selectedIncident.lat}, {selectedIncident.lon}</div>}
                      {(selectedIncident.threat || selectedIncident.commodity || selectedIncident.releaseGallons) && <div className="incident-detail__meta">{[selectedIncident.threat, selectedIncident.commodity, selectedIncident.releaseGallons ? `Reported max release: ${selectedIncident.releaseGallons} gal` : ''].filter(Boolean).join(' · ')}</div>}
                      <p>{selectedIncident.description || 'No incident description in this record.'}</p>
                      <details className="live-context-card">
                        <summary><strong>Find archived Sentinel-1 scenes</strong><span>Search official scene metadata near this location and date.</span></summary>
                        <div className="scene-search-fields">
                          <label>From <input type="date" value={sceneStart} onChange={(e) => setSceneStart(e.target.value)} /></label>
                          <label>To <input type="date" value={sceneEnd} onChange={(e) => setSceneEnd(e.target.value)} /></label>
                        </div>
                        <button className="incident-refresh" onClick={findSentinel1} disabled={disabled || sceneBusy || !sceneStart || !sceneEnd || selectedIncident.lat == null || selectedIncident.lon == null}>{sceneBusy ? 'Searching catalogue…' : 'Search Copernicus Data Space'}</button>
                        {sceneError && <div className="panel-state panel-state--error">{sceneError}</div>}
                        {sceneProducts && sceneProducts.length === 0 && <div className="panel-state panel-state--empty">No Sentinel-1 product matched this point and date window. {selectedIncident.date && selectedIncident.date < '2014-04-03' ? <>This record predates Sentinel-1A's 3 April 2014 launch; use an older SAR archive for that event. <a href="https://www.esa.int/Newsroom/Highlights/Sentinel-1A" target="_blank" rel="noreferrer">ESA mission details ↗</a></> : 'Try widening the date range or checking the incident coordinates.'}</div>}
                        {sceneProducts && sceneProducts.length > 0 && <div className="scene-results">{sceneProducts.map((product) => <div className="scene-result" key={product.id}><strong>{product.name}</strong><span>{product.start ? new Date(product.start).toLocaleString() : 'Acquisition time unavailable'} · {product.online ? 'online' : 'archive retrieval may be needed'}</span><code>{product.id}</code>{product.metadata_url && <a href={product.metadata_url} target="_blank" rel="noreferrer">Open product metadata ↗</a>}</div>)}</div>}
                        <div className="case-input__hint">Catalog metadata is not a detected oil slick. Download access and image processing are separate steps. NOAA's date is generally its notification date; confirm the actual spill/image time before analysis.</div>
                      </details>
                      <div className="live-context-card">
                        <div><strong>Current marine context</strong><span>Fetches present-day model conditions at this incident location.</span></div>
                        <button className="incident-refresh" onClick={loadLiveConditions} disabled={disabled || conditionsBusy || selectedIncident.lat == null || selectedIncident.lon == null}>{conditionsBusy ? 'Loading…' : 'Load current conditions'}</button>
                        {conditionsError && <div className="panel-state panel-state--error">{conditionsError}</div>}
                        {liveConditions && <>
                          <div className="live-context-card__values">
                            <span><small>Surface current</small><b>{liveConditions.forcing.current_speed_m_s.toFixed(2)} m/s · toward {liveConditions.forcing.current_direction_to_deg.toFixed(0)}°</b></span>
                            <span><small>Wind at 10 m</small><b>{liveConditions.forcing.wind_speed_m_s.toFixed(1)} m/s · from {liveConditions.forcing.wind_direction_from_deg.toFixed(0)}°</b></span>
                            <span><small>Model valid time</small><b>{liveConditions.model_time_utc ?? 'Not supplied'} UTC</b></span>
                          </div>
                          <div className="case-input__hint">{liveConditions.quality_note} Source: <a href="https://open-meteo.com/en/docs/marine-weather-api" target="_blank" rel="noreferrer">Open-Meteo Marine</a> / <a href="https://open-meteo.com/en/docs" target="_blank" rel="noreferrer">Weather API</a>; DWD attribution included.</div>
                        </>}
                      </div>
                      <div className="case-input__hint">This is historical incident metadata. It has no archived SAR slick outline, AIS tracks, or time-matched ocean forcing, so it cannot run the attribution pipeline by itself. Upload a complete replay package to run analysis.</div>
                    </article>
                  )}
                </div>
              )}
              <div className="case-input__source-note"><b>Data provenance</b><span>Bundled snapshot: incidents.csv. Use Refresh NOAA for the latest selected NOAA incident records (not a worldwide incident census). NOAA's open_date is usually its notification date, and coordinates can be approximate. The catalogue does not create vessel tracks or model outputs.</span><a href="https://incidentnews.noaa.gov/raw/index" target="_blank" rel="noreferrer">NOAA IncidentNews raw data ↗</a></div>
            </div>
          )}
          {inputTab === 'historical' && (
            <div className="case-input__history" role="tabpanel">
              <div className="case-input__history-head"><span className="history-mark">↺</span><div><strong>Replay a documented event</strong><span>Use recorded observations, vessel tracks, and time-matched forcing.</span></div></div>
              <label className="upload-drop">
                <input type="file" accept=".json,application/json" disabled={disabled || busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) handleHistoricalUpload(f); e.currentTarget.value = ''; }} />
                <span className="upload-drop__icon">＋</span>
                <span><b>{busy ? 'Importing historical case…' : 'Choose replay package'}</b><small>One JSON file · recorded AIS and current/wind samples required</small></span>
              </label>
              <div className="case-input__hint">Historical import preserves the event timestamp and records source references. Each layer is labeled real or provided from its package metadata. Missing data is never filled with synthetic tracks.</div>
              <a className="case-input__template" href="/historical_case_template.json" download>Download the JSON template ↓</a>
              <div className="case-input__source-note"><b>Prepare archive inputs</b><span>NOAA IncidentNews provides machine-readable incident records. Copernicus Marine provides historical ocean reanalysis; use the matching date and region. AIS must come from an authorized historical archive.</span><a href="https://incidentnews.noaa.gov/raw/index" target="_blank" rel="noreferrer">NOAA incident archive ↗</a><a href="https://data.marine.copernicus.eu/product/GLOBAL_MULTIYEAR_PHY_001_030/description" target="_blank" rel="noreferrer">Copernicus ocean reanalysis ↗</a></div>
            </div>
          )}
          {inputTab === 'scene' && (
            <div className="case-input__history" role="tabpanel">
              <label className="upload-drop upload-drop--compact">
                <input type="file" accept=".tif,.tiff" disabled={disabled || busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload(f); e.currentTarget.value = ''; }} />
                <span className="upload-drop__icon">＋</span>
                <span><b>Choose GeoTIFF scene</b><small>.tif or .tiff · supported single-band uncompressed formats</small></span>
              </label>
              <div className="case-input__hint">Runs the current classical dark-spot detector on the supplied raster. The app will label generated AIS as synthetic.</div>
            </div>
          )}
          {inputTab === 'synthetic' && (
            <div className="case-input__history" role="tabpanel">
          <div className="case-input__hint">Generates a reproducible test scenario. All generated inputs are labeled synthetic.</div>
          <div className="case-input__grid">
            <label>Lon (blank = auto) <input type="number" step="0.01" value={lon} onChange={(e) => setLon(e.target.value)} disabled={disabled || busy} /></label>
            <label>Lat (blank = auto) <input type="number" step="0.01" value={lat} onChange={(e) => setLat(e.target.value)} disabled={disabled || busy} /></label>
            <label>Release time (UTC) <input type="datetime-local" value={releaseTime} onChange={(e) => setReleaseTime(e.target.value)} disabled={disabled || busy} /></label>
            <label>Distractors <input type="number" min={0} max={10} value={nDistractors} onChange={(e) => setNDistractors(Number(e.target.value))} disabled={disabled || busy} /></label>
            <label>Gap rate <input type="number" min={0} max={0.9} step="0.05" value={gapRate} onChange={(e) => setGapRate(Number(e.target.value))} disabled={disabled || busy} /></label>
            <label>Seed <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} disabled={disabled || busy} /></label>
          </div>
          <button className="intro-panel__start" disabled={disabled || busy} onClick={handleGenerate}>
            {busy ? 'Generating…' : 'Generate synthetic case'}
          </button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
