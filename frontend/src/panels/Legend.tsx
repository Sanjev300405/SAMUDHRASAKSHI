import { useState } from 'react';

const STORAGE_KEY = 'ss.legend-open';

interface Row {
  key: string;
  swatch: React.ReactNode;
  label: string;
  note: string;
}

function readOpen(): boolean {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === null ? true : v === '1';
  } catch {
    return true;
  }
}

function writeOpen(open: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, open ? '1' : '0');
  } catch {
    /* private-mode / blocked storage — legend still works, just doesn't persist */
  }
}

interface Props {
  showObserved: boolean;
  showOrigin: boolean;
  showTraffic: boolean;
  showSimulated: boolean;
}

export default function Legend({ showObserved, showOrigin, showTraffic, showSimulated }: Props) {
  const [open, setOpen] = useState(readOpen);

  const rows: Row[] = [
    ...(showObserved ? [{
      key: 'observed',
      swatch: (
        <svg width="22" height="14" viewBox="0 0 22 14"><rect x="1" y="1" width="20" height="12" rx="2" fill="var(--slick)" fillOpacity={0.28} stroke="var(--slick)" strokeWidth={2.5} /></svg>
      ),
      label: 'Observed slick',
      note: 'What the satellite saw',
    }] : []),
    ...(showSimulated ? [{
      key: 'simulated',
      swatch: (
        <svg width="22" height="14" viewBox="0 0 22 14"><rect x="1" y="1" width="20" height="12" rx="2" fill="var(--sim)" fillOpacity={0.35} stroke="var(--sim)" strokeWidth={2} /></svg>
      ),
      label: 'Simulated slick',
      note: "Where this vessel's oil would have gone",
    }] : []),
    ...(showOrigin ? [{
      key: 'origin-hi',
      swatch: (
        <svg width="22" height="14" viewBox="0 0 22 14"><rect x="1" y="1" width="20" height="12" rx="2" fill="var(--origin-hi)" fillOpacity={0.22} stroke="var(--origin-hi)" strokeWidth={1.5} /></svg>
      ),
      label: 'High-probability origin',
      note: 'Most likely release area',
    }, {
      key: 'origin-md',
      swatch: (
        <svg width="22" height="14" viewBox="0 0 22 14"><rect x="1" y="1" width="20" height="12" rx="2" fill="var(--origin-lo)" fillOpacity={0.16} stroke="var(--origin-md)" strokeWidth={1.5} strokeDasharray="4 3" /></svg>
      ),
      label: 'Medium-probability origin',
      note: '',
    }] : []),
    ...(showTraffic ? [{
      key: 'vessel-ais',
      swatch: (
        <svg width="22" height="14" viewBox="0 0 22 14"><g transform="translate(11,7) rotate(90)"><path d="M0,-6 L4.5,5 L0,2.5 L-4.5,5 Z" fill="var(--track)" stroke="var(--s-void)" strokeWidth={0.75} /></g></svg>
      ),
      label: 'Vessel (AIS identified)',
      note: 'Arrow points to true heading',
    }, {
      key: 'vessel-dark',
      swatch: (
        <svg width="22" height="14" viewBox="0 0 22 14"><g transform="translate(11,7) rotate(90)"><path d="M0,-6 L4.5,5 L0,2.5 L-4.5,5 Z" fill="var(--dark-vessel)" stroke="var(--s-void)" strokeWidth={0.75} /></g></svg>
      ),
      label: 'Unidentified vessel',
      note: 'Radar contact, no AIS match',
    }, {
      key: 'track',
      swatch: (
        <svg width="22" height="14" viewBox="0 0 22 14"><line x1="1" y1="7" x2="21" y2="7" stroke="var(--track)" strokeWidth={1.5} /></svg>
      ),
      label: 'Vessel track',
      note: 'Up to the current time',
    }] : []),
  ];

  if (rows.length === 0) return null;

  return (
    <div className="panel e1 legend">
      <button className="legend__toggle" onClick={() => { const next = !open; setOpen(next); writeOpen(next); }} aria-expanded={open}>
        <span className="label" style={{ color: 'var(--fg-secondary)' }}>Legend</span>
        <span className="legend__chevron">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div className="legend__rows">
          {rows.map((r) => (
            <div key={r.key} className="legend__row">
              <span className="legend__swatch">{r.swatch}</span>
              <span className="legend__label">{r.label}</span>
              {r.note && <span className="legend__note">{r.note}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
