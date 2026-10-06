import { useEffect } from 'react';
import type { CandidateScore } from '../lib/types';
import { assertClean } from '../lib/lexicon';

const KIND_META: Record<string, { label: string; question: string }> = {
  spatial: { label: 'Spatial proximity', question: 'Was it near the likely origin?' },
  temporal: { label: 'Time overlap', question: 'Was it there during the window?' },
  trajectory: { label: 'Route alignment', question: 'Does its course match the slick axis?' },
  drift: { label: 'Drift compatibility', question: 'Could its oil have made this slick?' },
  behaviour: { label: 'Behaviour', question: 'Any unusual stops or turns?' },
};

const FOOTER = 'Evidence-based association only. Not legal proof.';

export default function EvidenceCard({ candidate }: { candidate: CandidateScore }) {
  const bars = candidate.evidence.filter((e) => e.supporting && e.kind in KIND_META);
  const maxContribution = Math.max(...bars.map((b) => b.weight_contribution), 0.001);

  useEffect(() => {
    for (const e of candidate.evidence) assertClean(e.label, 'EvidenceCard');
    for (const c of candidate.cautions) assertClean(c, 'EvidenceCard.cautions');
    assertClean(FOOTER, 'EvidenceCard.footer');
  }, [candidate]);

  return (
    <div className="panel evidence-card">
      <div className="label evidence-card__header">Why this vessel ranks here</div>
      {bars.map((e) => {
        const meta = KIND_META[e.kind];
        const isDrift = e.kind === 'drift';
        return (
          <div key={e.kind} className={`evidence-row${isDrift ? ' evidence-row--dominant' : ''}`} title={e.label}>
            <div className="evidence-row__text">
              <div className="evidence-row__label" style={isDrift ? { fontWeight: 500 } : undefined}>{meta.label}</div>
              <div className="evidence-row__question">{meta.question}</div>
            </div>
            <div className="evidence-row__measure">
              <div className="evidence-row__track">
                <div className="evidence-row__fill" style={{ width: `${(e.weight_contribution / maxContribution) * 100}%` }} />
              </div>
              <span className="num evidence-row__value">{e.weight_contribution.toFixed(3)}</span>
            </div>
          </div>
        );
      })}

      {candidate.cautions.length > 0 && (
        <div className="evidence-card__cautions">
          {candidate.cautions.map((c, i) => (
            <div key={i} className="caution-line" style={{ color: 'var(--caution)' }}>{c}</div>
          ))}
        </div>
      )}

      <div className="evidence-card__footer" style={{ fontFamily: 'var(--f-editorial)', fontStyle: 'italic' }}>
        {FOOTER}
      </div>
    </div>
  );
}
