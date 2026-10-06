import type { Provenance, Src } from '../lib/types';

const LABELS: Record<Src, string> = { real: 'REAL', provided: 'PROVIDED', synthetic: 'SYNTHETIC' };

type SourceMeta = { name?: string; url?: string; type?: string };
function Chip({ label, src, source }: { label: string; src: Src; source?: SourceMeta }) {
  const title = source ? [source.name, source.url].filter(Boolean).join(' · ') : undefined;
  return (
    <div className={`source-chip source-chip--${src}`} title={title}>
      <span className="label" style={{ color: 'var(--fg-tertiary)' }}>{label}</span>
      <span className="label" style={{ color: 'var(--fg-primary)' }}>{LABELS[src]}</span>
      {source?.name && (source.url
        ? <a className="source-chip__name" href={source.url} target="_blank" rel="noreferrer">{source.name} ↗</a>
        : <span className="source-chip__name">{source.name}</span>)}
    </div>
  );
}

export default function SourceChips({ provenance, sources }: { provenance: Provenance; sources?: Partial<Record<'sar' | 'ais' | 'forcing', SourceMeta>> }) {
  return (
    <div className="panel e1 source-chips">
      <Chip label="SAR" src={provenance.sar} source={sources?.sar} />
      <Chip label="FORCING" src={provenance.forcing} source={sources?.forcing} />
      <Chip label="AIS" src={provenance.ais} source={sources?.ais} />
    </div>
  );
}
