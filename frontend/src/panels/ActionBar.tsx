// Section B: the demo spine. One real button per ARCHITECTURE.md §8.1
// endpoint, mapped to steps 2/3/4/6/8 of §11's 8-step flow.
import type { StageKey, StageStatus } from '../lib/usePipeline';

interface ButtonSpec {
  key: StageKey;
  label: string;
}

const BUTTONS: ButtonSpec[] = [
  { key: 'detect', label: 'Detect' },
  { key: 'origin', label: 'Trace Origin' },
  { key: 'traffic', label: 'Analyse Traffic' },
  { key: 'simulate', label: 'Run Simulation' },
  { key: 'report', label: 'Report' },
];

interface Props {
  status: Record<StageKey, StageStatus>;
  progress: Partial<Record<StageKey, { current: number; total: number; message: string }>>;
  disabledReason: Partial<Record<StageKey, string>>;
  onRun: (stage: StageKey) => void;
}

export default function ActionBar({ status, progress, disabledReason, onRun }: Props) {
  return (
    <div className="panel e2 action-bar">
      {BUTTONS.map((b) => {
        const st = status[b.key];
        const reason = disabledReason[b.key];
        const disabled = st === 'running' || !!reason;
        const p = progress[b.key];
        const pct = p && p.total > 0 ? Math.round((p.current / p.total) * 100) : null;
        return (
          <button
            key={b.key}
            className={`action-bar__btn action-bar__btn--${st}`}
            disabled={disabled}
            title={reason ?? (st === 'done' ? `${b.label}: done -- click to re-run` : b.label)}
            onClick={() => onRun(b.key)}
          >
            {st === 'running' && (
              <span className="action-bar__progress" style={{ width: `${pct ?? 0}%` }} aria-hidden />
            )}
            <span className="action-bar__label">
              {st === 'done' && <span className="action-bar__check">&#10003; </span>}
              {b.label}
              {st === 'running' && pct !== null ? ` — ${pct}%` : ''}
            </span>
          </button>
        );
      })}
    </div>
  );
}
