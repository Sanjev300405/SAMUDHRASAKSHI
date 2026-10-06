import { useEffect } from 'react';
import { assertClean } from '../lib/lexicon';

const LINES = [
  'The satellite saw an oil slick.',
  'We ran the ocean backwards to find where it started.',
  'We found which ships were there at that time.',
  'For each ship we asked: would ITS oil have made THIS slick?',
];

const SWATCH: Record<number, string> = {
  0: 'var(--slick)',
  1: 'var(--origin-hi)',
  2: 'var(--track)',
  3: 'var(--sim)',
};

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function FirstRunExplainer({ open, onClose }: Props) {
  useEffect(() => {
    for (const l of LINES) assertClean(l, 'FirstRunExplainer');
  }, []);

  if (!open) return null;

  return (
    <div className="intro-overlay">
      <div className="panel e3 intro-panel">
        <ol className="intro-panel__lines">
          {LINES.map((line, i) => (
            <li key={i} className="intro-panel__line">
              <span className="intro-panel__num num" style={{ borderColor: SWATCH[i] }}>{i + 1}</span>
              <span>{line}</span>
            </li>
          ))}
        </ol>
        <button className="intro-panel__start" onClick={onClose}>Start</button>
      </div>
    </div>
  );
}
