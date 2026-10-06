import { useRef } from 'react';
import type { AISTrack, CandidateScore } from '../lib/types';
import { mmsi as fmtMmsi, titleCaseWord, vesselType } from '../lib/format';

const LEVEL_OPACITY: Record<CandidateScore['association_level'], number> = {
  high: 1.0,
  medium: 0.55,
  low: 0.28,
};

interface Props {
  candidates: CandidateScore[];
  tracks: AISTrack[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function CandidateList({ candidates, tracks, selectedId, onSelect }: Props) {
  const rowRefs = useRef<Array<HTMLDivElement | null>>([]);

  const move = (delta: number) => {
    const idx = candidates.findIndex((c) => c.candidate_id === selectedId);
    const next = Math.min(candidates.length - 1, Math.max(0, (idx < 0 ? 0 : idx) + delta));
    const cand = candidates[next];
    if (cand) {
      onSelect(cand.candidate_id);
      rowRefs.current[next]?.focus();
    }
  };

  return (
    <div className="panel candidate-list" role="listbox" aria-label="Candidate vessels">
      {candidates.map((c, i) => {
        const track = tracks.find((t) => t.track_id === c.track_id);
        const name = vesselType(track?.vessel_type ?? null);
        const isSelected = c.candidate_id === selectedId;
        return (
          <div
            key={c.candidate_id}
            ref={(el) => { rowRefs.current[i] = el; }}
            className={`candidate-row${isSelected ? ' candidate-row--selected' : ''}`}
            role="option"
            aria-selected={isSelected}
            tabIndex={0}
            onClick={() => onSelect(c.candidate_id)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
              else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
              else if (e.key === ' ') { e.preventDefault(); onSelect(c.candidate_id); }
            }}
          >
            <div className="candidate-row__id">
              <span className="label" style={{ color: 'var(--fg-secondary)' }}>{name}</span>
              <span className="num" style={{ color: 'var(--fg-tertiary)', fontSize: 'var(--t-micro)' }}>
                {fmtMmsi(track?.mmsi ?? null)}
              </span>
            </div>
            <div className="candidate-row__bar">
              <div
                className="candidate-row__bar-fill"
                style={{ width: `${c.association * 100}%`, opacity: LEVEL_OPACITY[c.association_level] }}
              />
            </div>
            <div className="candidate-row__score">
              <span className="num" style={{ fontSize: 'var(--t-data)' }}>{c.association.toFixed(2)}</span>
              <span className="label" style={{ color: 'var(--fg-tertiary)' }}>{titleCaseWord(c.association_level)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
