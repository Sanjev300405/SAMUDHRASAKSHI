import { useRef } from 'react';
import type { OriginEstimate } from '../lib/types';

interface Props {
  origin: OriginEstimate;
  observedAt: string;
  playheadMs: number;
  onScrub: (ms: number) => void;
}

export default function Timeline({ origin, observedAt, playheadMs, onScrub }: Props) {
  const trackRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const start = Date.parse(origin.window_start);
  const end = Date.parse(observedAt);
  const releaseStart = Date.parse(origin.window_start);
  const releaseEnd = Date.parse(origin.window_end);

  const pctOf = (ms: number) => ((ms - start) / (end - start)) * 100;

  const updateFromClientX = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    onScrub(start + frac * (end - start));
  };

  const ticks = Array.from({ length: 7 }, (_, i) => start + (i / 6) * (end - start));

  return (
    <div className="panel timeline">
      <div
        className="timeline__track"
        ref={trackRef}
        onPointerDown={(e) => { dragging.current = true; (e.target as Element).setPointerCapture(e.pointerId); updateFromClientX(e.clientX); }}
        onPointerMove={(e) => { if (dragging.current) updateFromClientX(e.clientX); }}
        onPointerUp={() => { dragging.current = false; }}
      >
        <div
          className="timeline__release-band"
          style={{ left: `${pctOf(releaseStart)}%`, width: `${pctOf(releaseEnd) - pctOf(releaseStart)}%` }}
        />
        <div className="timeline__playhead" style={{ left: `${pctOf(playheadMs)}%` }} />
        {ticks.map((t) => (
          <div key={t} className="timeline__tick" style={{ left: `${pctOf(t)}%` }}>
            <span className="num">{new Date(t).toISOString().slice(11, 16)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
