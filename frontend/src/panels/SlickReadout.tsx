import type { SlickObservation } from '../lib/types';

export default function SlickReadout({ observation }: { observation: SlickObservation }) {
  return (
    <div className="panel slick-readout">
      <div className="slick-readout__value">
        <span className="num" style={{ fontSize: 'var(--t-data-lg)' }}>{observation.area_km2.toFixed(1)}</span>
        <span className="label" style={{ color: 'var(--fg-tertiary)', marginLeft: 6 }}>km&sup2;</span>
      </div>
      <div className="slick-readout__meta">
        <span className="chip">{observation.classification}</span>
        <span className="num" style={{ color: 'var(--fg-secondary)' }}>{(observation.confidence * 100).toFixed(0)}% confidence</span>
      </div>
    </div>
  );
}
