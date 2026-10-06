import { useEffect, useState } from 'react';
import { usePipeline, STAGE_ORDER, type StageKey } from './lib/usePipeline';
import * as api from './lib/api';
import MapScene from './map/MapScene';
import SlickReadout from './panels/SlickReadout';
import SourceChips from './panels/SourceChips';
import CandidateList from './panels/CandidateList';
import TrafficList from './panels/TrafficList';
import EvidenceCard from './panels/EvidenceCard';
import SwipeComparator from './panels/SwipeComparator';
import Timeline from './panels/Timeline';
import VerdictLine from './panels/VerdictLine';
import Legend from './panels/Legend';
import FirstRunExplainer from './panels/FirstRunExplainer';
import ActionBar from './panels/ActionBar';
import CaseInputPanel from './panels/CaseInputPanel';
import PanelState from './panels/PanelState';

const INTRO_KEY = 'ss.seen-intro';

const STAGES: { id: StageKey; label: string }[] = [
  { id: 'detect', label: 'Detect' },
  { id: 'origin', label: 'Origin' },
  { id: 'traffic', label: 'Traffic' },
  { id: 'simulate', label: 'Simulate' },
  { id: 'report', label: 'Report' },
];

const STAGE_GLYPH: Record<string, React.ReactNode> = {
  detect: <circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" />,
  origin: <path d="M4 16 Q8 10 12 16 T20 16" fill="none" stroke="currentColor" strokeWidth="1.5" />,
  traffic: <path d="M6 18 L12 5 L18 18 Z" fill="none" stroke="currentColor" strokeWidth="1.5" />,
  simulate: <path d="M4 12 C4 8 8 8 8 12 S12 16 12 12 16 8 16 12 20 16 20 12" fill="none" stroke="currentColor" strokeWidth="1.5" />,
  report: <path d="M6 4 H16 V20 H6 Z M8 8 H14 M8 12 H14 M8 16 H11" fill="none" stroke="currentColor" strokeWidth="1.5" />,
};

function readIntroSeen(): boolean {
  try { return localStorage.getItem(INTRO_KEY) === '1'; } catch { return false; }
}

function Rail({ stage, maxCompleted, onView, onReopenDock, onHelp, onCase }: {
  stage: StageKey | null; maxCompleted: StageKey | null; onView: (s: StageKey) => void; onReopenDock: () => void; onHelp: () => void; onCase: () => void;
}) {
  const maxIdx = maxCompleted ? STAGE_ORDER.indexOf(maxCompleted) : -1;
  return (
    <nav className="rail" aria-label="Stage navigation">
      <button className="rail__icon" aria-label="Choose case" onClick={onCase}>
        <svg width="24" height="24" viewBox="0 0 24 24">
          <rect x="4" y="5" width="16" height="14" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M4 9 H20" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>
      {STAGES.map((s, i) => {
        const enabled = i <= maxIdx;
        return (
          <button
            key={s.id}
            className={`rail__icon${stage === s.id ? ' rail__icon--active' : ''}`}
            aria-label={s.label}
            aria-current={stage === s.id}
            disabled={!enabled}
            title={enabled ? s.label : `${s.label} — not reached yet`}
            onClick={() => { onView(s.id); onReopenDock(); }}
          >
            <svg width="24" height="24" viewBox="0 0 24 24">{STAGE_GLYPH[s.id]}</svg>
          </button>
        );
      })}
      <button className="rail__icon rail__help" aria-label="Show introduction" onClick={onHelp}>
        <svg width="24" height="24" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M9.5 9.2c0-1.3 1.1-2.3 2.5-2.3s2.5.9 2.5 2.1c0 1.6-2.2 1.6-2.4 3.3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="12" cy="16.3" r="0.9" fill="currentColor" />
        </svg>
      </button>
    </nav>
  );
}

export default function App() {
  const p = usePipeline('demo');
  const [selectedTrackId, setSelectedTrackId] = useState<string | null>(null);
  const [playheadMs, setPlayheadMs] = useState<number | null>(null);
  const [dockOpen, setDockOpen] = useState(true);
  const [introOpen, setIntroOpen] = useState(() => !readIntroSeen());
  const [caseInputOpen, setCaseInputOpen] = useState(false);

  useEffect(() => {
    if (p.origin && playheadMs === null) setPlayheadMs(Date.parse(p.origin.window_start));
  }, [p.origin, playheadMs]);

  useEffect(() => {
    if (p.candidates && p.candidates.length > 0 && !selectedTrackId) setSelectedTrackId(p.candidates[0].track_id);
  }, [p.candidates, selectedTrackId]);

  useEffect(() => {
    if (p.tracks && p.tracks.length > 0 && !selectedTrackId) setSelectedTrackId(p.tracks[0].track_id);
  }, [p.tracks, selectedTrackId]);

  useEffect(() => {
    // Don't stack this on top of the first-run intro -- open it once that's
    // dismissed, not simultaneously (two overlays open at once is bad UX,
    // and their close buttons happen to share a class name too).
    if (p.mode === 'live' && !p.caseId && !introOpen) setCaseInputOpen(true);
  }, [p.mode, p.caseId, introOpen]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setDockOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const closeIntro = () => {
    setIntroOpen(false);
    try { localStorage.setItem(INTRO_KEY, '1'); } catch { /* ignore */ }
  };

  if (p.mode === 'checking') {
    return <div className="app-status">Connecting&hellip;</div>;
  }

  const stage = p.stage;
  const stageIdx = stage ? STAGE_ORDER.indexOf(stage) : -1;
  const at = (s: StageKey) => stageIdx >= STAGE_ORDER.indexOf(s);

  const selectedCandidate = p.candidates?.find((c) => c.track_id === selectedTrackId) ?? null;
  const sourceMetadata = p.observation && 'source_metadata' in p.observation
    ? (p.observation as unknown as { source_metadata?: Partial<Record<'sar' | 'ais' | 'forcing', { name?: string; url?: string; type?: string }>> }).source_metadata
    : undefined;
  const selectedTrack = (p.tracks ?? []).find((t) => t.track_id === selectedTrackId);
  const isTopRanked = p.candidates?.[0]?.track_id === selectedTrackId;

  const noReachableTracks = at('traffic') && p.tracks !== null && p.tracks.length === 0;
  const disabledPrereq = p.disabledReason;

  return (
    <div className="app grain">
      <Rail
        stage={stage} maxCompleted={p.maxCompleted}
        onView={p.setStage} onReopenDock={() => setDockOpen(true)}
        onHelp={() => setIntroOpen(true)} onCase={() => setCaseInputOpen(true)}
      />

      <div className="map-dock-area">
        <main className="map-area">
          <MapScene
            observation={p.observation} origin={p.origin} tracks={p.tracks} candidates={p.candidates}
            selectedTrackId={selectedTrackId} playheadMs={playheadMs} onSelectVessel={setSelectedTrackId}
            showOrigin={at('origin')} showTraffic={at('traffic')} showSimulated={at('simulate')}
          />

          <div className="mode-badge num" data-mode={p.mode}>{p.mode === 'live' ? 'LIVE' : 'OFFLINE (cached demo)'}</div>
          {p.provenance && Object.values(p.provenance).some((source) => source === 'synthetic') && (
            <div className="sample-data-banner" role="status">SAMPLE SCENARIO · SYNTHETIC INPUTS</div>
          )}

          {p.observation && (
            <div className="map-area__slick-readout"><SlickReadout observation={p.observation} /></div>
          )}
          {p.provenance && (
            <div className="map-area__source-chips"><SourceChips provenance={p.provenance} sources={sourceMetadata} /></div>
          )}
          <div className="map-area__legend">
            <Legend showObserved={!!p.observation} showOrigin={at('origin') && !!p.origin} showTraffic={at('traffic') && !!p.tracks?.length} showSimulated={at('simulate') && !!selectedCandidate?.best_release} />
          </div>
          <div className="map-area__timeline">
            <div className="panel timeline-shell">
              {p.origin && p.observation ? (
                <Timeline origin={p.origin} observedAt={p.observation.observed_at} playheadMs={playheadMs ?? Date.parse(p.origin.window_start)} onScrub={setPlayheadMs} />
              ) : (
                <PanelState status="idle" idleMessage="Trace Origin to see the release window." />
              )}
            </div>
          </div>

          <ActionBar status={p.status} progress={p.progress} disabledReason={disabledPrereq} onRun={(s) => p.run[s]()} />
        </main>

        {dockOpen && (
          <aside className="dock panel">
            <div className="dock__wordmark">
              <div style={{ fontFamily: 'var(--f-editorial)', fontStyle: 'italic', letterSpacing: '0.06em', fontSize: 'var(--t-h1)', color: 'var(--fg-primary)' }}>
                SAMUDRA SAKSHI
              </div>
              <div className="label" style={{ color: 'var(--fg-tertiary)' }}>&mdash; THE OCEAN WITNESS &mdash;</div>
            </div>

            {selectedCandidate && at('simulate') && (
              <VerdictLine candidate={selectedCandidate} track={selectedTrack} isTopRanked={isTopRanked} />
            )}

            <div className="dock__section">
              <PanelState
                status={p.status.traffic === 'error' ? 'error' : p.status.traffic === 'running' ? 'loading' : at('traffic') && p.tracks ? (p.tracks.length === 0 ? 'empty' : 'ready') : 'idle'}
                progress={p.progress.traffic}
                idleMessage="Analyse Traffic to see candidate vessels."
                emptyMessage={p.trafficEmptyReason ?? 'No candidates met the reachability filter'}
                errorMessage={p.errors.traffic}
              >
                {at('simulate') && p.candidates ? (
                  <CandidateList
                    candidates={p.candidates} tracks={p.tracks ?? []}
                    selectedId={p.candidates.find((c) => c.track_id === selectedTrackId)?.candidate_id ?? null}
                    onSelect={(candId) => { const t = p.candidates?.find((c) => c.candidate_id === candId)?.track_id; if (t) setSelectedTrackId(t); }}
                  />
                ) : (
                  p.tracks && <TrafficList tracks={p.tracks} selectedTrackId={selectedTrackId} onSelect={setSelectedTrackId} />
                )}
              </PanelState>
            </div>

            <div className="dock__section">
              <PanelState
                status={p.status.simulate === 'error' ? 'error' : p.status.simulate === 'running' ? 'loading' : noReachableTracks ? 'empty' : at('simulate') && p.candidates ? (selectedCandidate ? 'ready' : 'empty') : 'idle'}
                progress={p.progress.simulate}
                idleMessage="Run Simulation to see the evidence for the selected vessel."
                emptyMessage={noReachableTracks ? 'No AIS track passed the reachability filter, so there is nothing to simulate. Check the replay AIS timestamps and coordinates against the origin window. Incident catalog entries need a complete replay package.' : 'Select a candidate to see its evidence.'}
                errorMessage={p.errors.simulate}
              >
                {selectedCandidate && (
                  <>
                    <EvidenceCard candidate={selectedCandidate} />
                    <div className="dock__comparator">
                      {p.observation && <SwipeComparator candidate={selectedCandidate} observedGeometry={p.observation.geometry} />}
                    </div>
                  </>
                )}
              </PanelState>
            </div>

            {at('report') && p.caseId && (
              <div className="dock__section">
                <div className="panel report-preview">
                  <div className="label" style={{ color: 'var(--fg-tertiary)', marginBottom: 8 }}>Report</div>
                  {p.mode === 'live' ? (
                    <div className="report-preview__links">
                      <a href={api.reportPdfUrl(p.caseId)} target="_blank" rel="noreferrer">Download report.pdf</a>
                      <a href={api.exportGeojsonUrl(p.caseId)} target="_blank" rel="noreferrer">Download export.geojson</a>
                    </div>
                  ) : (
                    <div className="panel-state panel-state--degraded">Offline mode: report generation needs the live API.</div>
                  )}
                  <div className="evidence-card__footer" style={{ fontFamily: 'var(--f-editorial)', fontStyle: 'italic' }}>
                    Evidence-based association only. Not legal proof.
                  </div>
                </div>
              </div>
            )}
          </aside>
        )}
      </div>

      <CaseInputPanel
        open={caseInputOpen} onClose={() => setCaseInputOpen(false)}
        onSelectCase={p.selectCase} disabled={p.mode === 'offline'}
      />
      <FirstRunExplainer open={introOpen} onClose={closeIntro} />
    </div>
  );
}
