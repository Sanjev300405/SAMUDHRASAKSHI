// Section C: "traffic -> + candidate list" -- at this stage M6/M8 haven't
// run yet, so there is no association score. Shows real M5 output (vessel
// identity + AIS quality) honestly, without inventing a score.
import type { AISTrack } from '../lib/types';
import { mmsi as fmtMmsi, vesselType } from '../lib/format';

export default function TrafficList({ tracks, selectedTrackId, onSelect }: { tracks: AISTrack[]; selectedTrackId: string | null; onSelect: (trackId: string) => void }) {
  return (
    <div className="panel candidate-list" role="listbox" aria-label="AIS traffic">
      {tracks.map((t) => (
        <div
          key={t.track_id}
          className={`candidate-row${selectedTrackId === t.track_id ? ' candidate-row--selected' : ''}`}
          role="option" aria-selected={selectedTrackId === t.track_id} tabIndex={0}
          onClick={() => onSelect(t.track_id)}
        >
          <div className="candidate-row__id">
            <span className="label" style={{ color: 'var(--fg-secondary)' }}>{vesselType(t.vessel_type)}</span>
            <span className="num" style={{ color: 'var(--fg-tertiary)', fontSize: 'var(--t-micro)' }}>{fmtMmsi(t.mmsi)}</span>
          </div>
          <div className="candidate-row__bar">
            <div className="candidate-row__bar-fill" style={{ width: `${t.quality.score * 100}%`, opacity: 0.6 }} />
          </div>
          <div className="candidate-row__score">
            <span className="num" style={{ fontSize: 'var(--t-data)', color: 'var(--fg-tertiary)' }}>Q {t.quality.score.toFixed(2)}</span>
            <span className="label" style={{ color: 'var(--fg-tertiary)' }}>pending</span>
          </div>
        </div>
      ))}
    </div>
  );
}
