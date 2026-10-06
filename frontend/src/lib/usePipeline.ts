// The demo-flow state machine (ARCHITECTURE.md §11's 8 steps + section C's
// stage-driven layer accumulation). Works identically in both modes:
//   live    -- each stage action calls the real API and waits on real progress
//   offline -- each stage action instantly copies the matching slice out of
//              the already-loaded cached bundle.json (ADR-004, section F) --
//              same choreography, zero network calls.
import { useCallback, useEffect, useState } from 'react';
import * as api from './api';
import type { AISTrack, CandidateScore, CaseBundle, OriginEstimate, Provenance, SlickObservation } from './types';

export type StageKey = 'detect' | 'origin' | 'traffic' | 'simulate' | 'report';
export const STAGE_ORDER: StageKey[] = ['detect', 'origin', 'traffic', 'simulate', 'report'];
export type StageStatus = 'idle' | 'running' | 'done' | 'error';
export type Progress = { current: number; total: number; message: string };
export type Mode = 'checking' | 'live' | 'offline';

const emptyStatus = (): Record<StageKey, StageStatus> => ({ detect: 'idle', origin: 'idle', traffic: 'idle', simulate: 'idle', report: 'idle' });

function offlineRequested(): boolean {
  const q = new URLSearchParams(window.location.search).get('offline');
  return q === '1' || q === 'true';
}

export function usePipeline(defaultOfflineCaseId = 'demo') {
  const [mode, setMode] = useState<Mode>('checking');
  const [caseId, setCaseId] = useState<string | null>(null);
  const [cachedBundle, setCachedBundle] = useState<CaseBundle | null>(null);

  const [observation, setObservation] = useState<SlickObservation | null>(null);
  const [origin, setOrigin] = useState<OriginEstimate | null>(null);
  const [tracks, setTracks] = useState<AISTrack[] | null>(null);
  const [candidates, setCandidates] = useState<CandidateScore[] | null>(null);
  const [provenance, setProvenance] = useState<Provenance | null>(null);
  const [trafficEmptyReason, setTrafficEmptyReason] = useState<string | null>(null);

  const [stage, setStage] = useState<StageKey | null>(null); // currently VIEWED stage
  const [maxCompleted, setMaxCompleted] = useState<StageKey | null>(null);
  const [status, setStatus] = useState<Record<StageKey, StageStatus>>(emptyStatus());
  const [progress, setProgress] = useState<Partial<Record<StageKey, Progress>>>({});
  const [errors, setErrors] = useState<Partial<Record<StageKey, string>>>({});

  // --- mode detection: offline query param wins; otherwise probe the API ---
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (offlineRequested()) {
        if (!cancelled) setMode('offline');
        return;
      }
      const alive = await api.checkHealth();
      if (cancelled) return;
      setMode(alive ? 'live' : 'offline');
    })();
    return () => { cancelled = true; };
  }, []);

  // --- offline: load the cached bundle once we know we're offline ---
  useEffect(() => {
    if (mode !== 'offline') return;
    let cancelled = false;
    fetch(`/cases/${defaultOfflineCaseId}/bundle.json`)
      .then((r) => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); })
      .then((b: CaseBundle) => { if (!cancelled) { setCachedBundle(b); setCaseId(b.case_id); } })
      .catch((e) => { if (!cancelled) setErrors((prev) => ({ ...prev, detect: `Failed to load cached bundle: ${e}` })); });
    return () => { cancelled = true; };
  }, [mode, defaultOfflineCaseId]);

  const reset = useCallback(() => {
    setObservation(null); setOrigin(null); setTracks(null); setCandidates(null);
    setProvenance(null); setTrafficEmptyReason(null);
    setStage(null); setMaxCompleted(null);
    setStatus(emptyStatus()); setProgress({}); setErrors({});
  }, []);

  const selectCase = useCallback((id: string) => {
    reset();
    setCaseId(id);
  }, [reset]);

  const advanceTo = (s: StageKey) => {
    setStage(s);
    setMaxCompleted((prev) => {
      const prevIdx = prev ? STAGE_ORDER.indexOf(prev) : -1;
      const newIdx = STAGE_ORDER.indexOf(s);
      return newIdx > prevIdx ? s : prev;
    });
  };

  const setRunning = (s: StageKey, p?: Progress) => {
    setStatus((prev) => ({ ...prev, [s]: 'running' }));
    if (p) setProgress((prev) => ({ ...prev, [s]: p }));
    setErrors((prev) => ({ ...prev, [s]: undefined }));
  };
  const setDone = (s: StageKey) => setStatus((prev) => ({ ...prev, [s]: 'done' }));
  const setError = (s: StageKey, msg: string) => {
    setStatus((prev) => ({ ...prev, [s]: 'error' }));
    setErrors((prev) => ({ ...prev, [s]: msg }));
  };

  const runDetect = useCallback(async () => {
    if (!caseId) return;
    setRunning('detect');
    try {
      if (mode === 'offline') {
        if (!cachedBundle) throw new Error('cached bundle not loaded yet');
        setObservation(cachedBundle.observation);
        setProvenance(cachedBundle.provenance);
      } else {
        const obs = await api.runDetect(caseId);
        setObservation(obs);
        setProvenance(obs.provenance); // real, server-tracked (upload vs synthetic), not assumed client-side
      }
      setDone('detect');
      advanceTo('detect');
    } catch (e) {
      setError('detect', e instanceof Error ? e.message : String(e));
    }
  }, [caseId, mode, cachedBundle]);

  const runOrigin = useCallback(async () => {
    if (!caseId) return;
    setRunning('origin', { current: 0, total: 1, message: 'Starting hindcast…' });
    try {
      if (mode === 'offline') {
        if (!cachedBundle) throw new Error('cached bundle not loaded yet');
        await new Promise((r) => setTimeout(r, 250)); // let the loading state be visible even offline
        setOrigin(cachedBundle.origin);
      } else {
        const jobId = await api.startHindcast(caseId);
        const result = await api.pollJob<OriginEstimate>(jobId, (current, total, message) => setProgress((prev) => ({ ...prev, origin: { current, total, message } })));
        setOrigin(result);
      }
      setDone('origin');
      advanceTo('origin');
    } catch (e) {
      setError('origin', e instanceof Error ? e.message : String(e));
    }
  }, [caseId, mode, cachedBundle]);

  const runTraffic = useCallback(async () => {
    if (!caseId) return;
    // Traffic reruns invalidate any previously selected candidate/evidence.
    setCandidates(null);
    setStatus((prev) => ({ ...prev, simulate: 'idle', report: 'idle' }));
    setRunning('traffic', { current: 0, total: 1, message: 'Filtering AIS traffic…' });
    try {
      if (mode === 'offline') {
        if (!cachedBundle) throw new Error('cached bundle not loaded yet');
        await new Promise((r) => setTimeout(r, 250));
        setTracks(cachedBundle.tracks);
        if (cachedBundle.tracks.length === 0) setTrafficEmptyReason('No AIS track overlaps the estimated origin window and reachable area. Check the archived AIS dates and coordinates.');
      } else {
        const result = await api.runTraffic(caseId);
        setTracks(result.tracks);
        if (result.tracks.length === 0) setTrafficEmptyReason('No AIS track overlaps the estimated origin window and reachable area. Check the archived AIS dates and coordinates.');
      }
      setDone('traffic');
      advanceTo('traffic');
    } catch (e) {
      setError('traffic', e instanceof Error ? e.message : String(e));
    }
  }, [caseId, mode, cachedBundle]);

  const runSimulate = useCallback(async () => {
    if (!caseId) return;
    if (!tracks || tracks.length === 0) {
      setError('simulate', 'Simulation needs at least one reachable AIS track. Check AIS timestamps and coordinates, then run Analyse Traffic again.');
      return;
    }
    setRunning('simulate', { current: 0, total: 1, message: 'Seeding counterfactual hypotheses…' });
    try {
      if (mode === 'offline') {
        if (!cachedBundle) throw new Error('cached bundle not loaded yet');
        await new Promise((r) => setTimeout(r, 250));
        setCandidates(cachedBundle.candidates);
      } else {
        const jobId = await api.startSimulate(caseId);
        const result = await api.pollJob<CandidateScore[]>(jobId, (current, total, message) => setProgress((prev) => ({ ...prev, simulate: { current, total, message } })));
        setCandidates(result);
      }
      setDone('simulate');
      advanceTo('simulate');
    } catch (e) {
      setError('simulate', e instanceof Error ? e.message : String(e));
    }
  }, [caseId, mode, cachedBundle, tracks]);

  const runReport = useCallback(async () => {
    if (!caseId) return;
    setRunning('report');
    try {
      if (mode === 'live') {
        // touch the endpoint once so the server has generated/validated the PDF before we link to it
        await fetch(api.reportPdfUrl(caseId), { method: 'GET' });
      }
      setDone('report');
      advanceTo('report');
    } catch (e) {
      setError('report', e instanceof Error ? e.message : String(e));
    }
  }, [caseId, mode]);

  const runners: Record<StageKey, () => void> = {
    detect: runDetect, origin: runOrigin, traffic: runTraffic, simulate: runSimulate, report: runReport,
  };

  const prerequisiteMessage: Record<StageKey, string> = {
    detect: 'Select or create a case first',
    origin: 'Trace Origin needs a detected slick first',
    traffic: 'Analyse Traffic needs the origin estimate first',
    simulate: 'Run Simulation needs AIS traffic analysed first',
    report: 'Report needs a completed simulation first',
  };

  const disabledReason: Partial<Record<StageKey, string>> = {};
  if (!caseId) {
    for (const s of STAGE_ORDER) disabledReason[s] = 'Select or create a case first';
  } else {
    const maxIdx = maxCompleted ? STAGE_ORDER.indexOf(maxCompleted) : -1;
    STAGE_ORDER.forEach((s, i) => {
      if (i > maxIdx + 1) disabledReason[s] = prerequisiteMessage[s];
    });
  }
  if (status.traffic === 'done' && tracks !== null && tracks.length === 0) {
    disabledReason.simulate = 'No AIS track passed reachability; check archived AIS dates and coordinates.';
  }

  return {
    mode, caseId, selectCase,
    observation, origin, tracks, candidates, provenance, trafficEmptyReason,
    stage, setStage, maxCompleted,
    status, progress, errors,
    disabledReason,
    run: runners,
  };
}
