// Real client for backend/api/main.py — every function here calls a real
// FastAPI endpoint backed by real pipeline code; none fabricate a response.
import type { AISTrack, CandidateScore, SlickObservation } from './types';

const API_BASE = (import.meta as unknown as { env: Record<string, string | undefined> }).env.VITE_API_BASE ?? 'http://localhost:8000';

export class ApiError extends Error {}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* ignore */ }
    throw new ApiError(detail);
  }
  return res.json() as Promise<T>;
}

export async function checkHealth(timeoutMs = 1500): Promise<boolean> {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const res = await fetch(`${API_BASE}/api/v1/health`, { signal: ctrl.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}

export interface CaseListing { case_id: string; has_raw_input: boolean; has_bundle: boolean }

export async function listCases(): Promise<CaseListing[]> {
  const res = await fetch(`${API_BASE}/api/v1/cases`);
  const data = await asJson<{ cases: CaseListing[] }>(res);
  return data.cases;
}

export interface SyntheticCaseParams {
  lon?: number; lat?: number; releaseTime?: string; durationH?: number;
  nDistractors?: number; gapRate?: number; loiterRate?: number; seed?: number;
}

export async function createSyntheticCase(p: SyntheticCaseParams): Promise<{ case_id: string; release_lon: number; release_lat: number; release_time: string; n_tracks: number }> {
  const q = new URLSearchParams();
  if (p.lon !== undefined) q.set('lon', String(p.lon));
  if (p.lat !== undefined) q.set('lat', String(p.lat));
  if (p.releaseTime) q.set('release_time', p.releaseTime);
  if (p.durationH !== undefined) q.set('duration_h', String(p.durationH));
  if (p.nDistractors !== undefined) q.set('n_distractors', String(p.nDistractors));
  if (p.gapRate !== undefined) q.set('gap_rate', String(p.gapRate));
  if (p.loiterRate !== undefined) q.set('loiter_rate', String(p.loiterRate));
  if (p.seed !== undefined) q.set('seed', String(p.seed));
  const res = await fetch(`${API_BASE}/api/v1/cases/synthetic?${q}`, { method: 'POST' });
  return asJson(res);
}

export async function uploadGeoTiff(file: File, nTracks = 4): Promise<{ case_id: string; n_tracks: number }> {
  const form = new FormData();
  form.append('file', file);
  form.append('n_tracks', String(nTracks));
  const res = await fetch(`${API_BASE}/api/v1/cases`, { method: 'POST', body: form });
  return asJson(res);
}

export async function uploadHistoricalCase(file: File): Promise<{ case_id: string; n_tracks: number; n_forcing_samples: number }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/api/v1/cases/historical`, { method: 'POST', body: form });
  return asJson(res);
}

export interface LiveIncidentRecord {
  id: string; date: string; name: string; location: string;
  lat: number | null; lon: number | null; threat: string;
  commodity: string; releaseGallons: string; description: string; tags: string;
}

export async function refreshLiveIncidents(): Promise<{ records: LiveIncidentRecord[]; record_count: number; fetched_at_utc: string; source: { name: string; url: string; type: string } }> {
  const res = await fetch(`${API_BASE}/api/v1/live/incidents?refresh=true`);
  return asJson(res);
}

export interface LiveConditions {
  retrieved_at_utc: string; model_time_utc: string | null;
  requested_location: { lat: number; lon: number };
  classification: string;
  forcing: { current_speed_m_s: number; current_direction_to_deg: number; current_u_m_s: number; current_v_m_s: number; wind_speed_m_s: number; wind_direction_from_deg: number; wind_u_m_s: number; wind_v_m_s: number };
  sources: Array<{ name: string; url: string }>;
  quality_note: string;
}

export async function getLiveConditions(lat: number, lon: number): Promise<LiveConditions> {
  const q = new URLSearchParams({ lat: String(lat), lon: String(lon) });
  const res = await fetch(`${API_BASE}/api/v1/live/conditions?${q}`);
  return asJson(res);
}

export interface Sentinel1Product {
  id: string; name: string; start: string | null; end: string | null;
  online: boolean | null; metadata_url: string | null;
}

export async function searchSentinel1(lat: number, lon: number, startDate: string, endDate: string): Promise<{ products: Sentinel1Product[]; count: number; note: string; fetched_at_utc: string }> {
  const q = new URLSearchParams({ lat: String(lat), lon: String(lon), start_date: startDate, end_date: endDate });
  const res = await fetch(`${API_BASE}/api/v1/live/sentinel1?${q}`);
  return asJson(res);
}

export async function runDetect(caseId: string): Promise<SlickObservation> {
  const res = await fetch(`${API_BASE}/api/v1/cases/${caseId}/detect`, { method: 'POST' });
  return asJson(res);
}

export async function runTraffic(caseId: string): Promise<{ tracks: AISTrack[]; n_filtered_out: number }> {
  const res = await fetch(`${API_BASE}/api/v1/cases/${caseId}/traffic`, { method: 'POST' });
  return asJson(res);
}

export interface JobStatus<T> {
  job_id: string;
  status: 'running' | 'done' | 'error';
  progress: { current: number; total: number; message: string };
  result: T | null;
  error: string | null;
}

async function startJob(url: string): Promise<string> {
  const res = await fetch(url, { method: 'POST' });
  const data = await asJson<{ job_id: string }>(res);
  return data.job_id;
}

export async function pollJob<T>(jobId: string, onProgress?: (current: number, total: number, message: string) => void, signal?: AbortSignal): Promise<T> {
  for (;;) {
    if (signal?.aborted) throw new ApiError('cancelled');
    const res = await fetch(`${API_BASE}/api/v1/jobs/${jobId}`, { signal });
    const data = await asJson<JobStatus<T>>(res);
    onProgress?.(data.progress.current, data.progress.total, data.progress.message);
    if (data.status === 'done') return data.result as T;
    if (data.status === 'error') throw new ApiError(data.error ?? 'job failed');
    await new Promise((r) => setTimeout(r, 350));
  }
}

export async function startHindcast(caseId: string, ensemble = 30, particles = 500): Promise<string> {
  return startJob(`${API_BASE}/api/v1/cases/${caseId}/hindcast?ensemble=${ensemble}&particles=${particles}`);
}

export async function startSimulate(caseId: string, particlesPerRelease = 100): Promise<string> {
  return startJob(`${API_BASE}/api/v1/cases/${caseId}/simulate?particles_per_release=${particlesPerRelease}`);
}

export function reportPdfUrl(caseId: string): string {
  return `${API_BASE}/api/v1/cases/${caseId}/report.pdf`;
}

export function exportGeojsonUrl(caseId: string): string {
  return `${API_BASE}/api/v1/cases/${caseId}/export.geojson`;
}

export async function getFullBundle(caseId: string) {
  const res = await fetch(`${API_BASE}/api/v1/cases/${caseId}`);
  return asJson(res);
}

export { API_BASE };
export type { CandidateScore, AISTrack, SlickObservation };
