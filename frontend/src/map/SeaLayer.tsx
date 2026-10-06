import { useMemo } from 'react';

/**
 * SeaLayer — animated open-ocean backdrop for the map.
 *
 * Constraints this layer works under:
 *  - It sits BEHIND every data layer and tops out around 14% opacity, so it
 *    cannot compete with the slick, the origin field or the vessel tracks.
 *    The map is an instrument first. Values here were tuned by rendering the
 *    layer with sample data on top and checking legibility, not by eye-balling.
 *  - It renders in SCREEN space, outside MapScene's pan/zoom transform. Water
 *    that scaled with the camera would read as texture stuck to the seabed
 *    rather than as a surface.
 *  - Wave rows use a seeded PRNG for phase, amplitude, period and opacity.
 *    Evenly-spaced identical rows read as scanlines, not sea.
 *  - Motion is CSS transform on five groups (GPU-composited). No animated
 *    feTurbulence, no canvas, no new dependency -- an animated displacement
 *    filter over a full-screen rect is the one thing here that would cost frames.
 *  - prefers-reduced-motion freezes it; see index.css.
 *
 * To render a flat ocean instead, set SEA_ANIMATED = false in MapScene.
 */

interface Props {
  width: number;
  height: number;
  enabled?: boolean;
}

/** mulberry32 — small deterministic PRNG so the sea is stable across renders. */
function prng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function sinePath(width: number, y: number, amp: number, period: number, phase: number): string {
  const step = period / 14;
  let d = `M0,${y.toFixed(2)}`;
  for (let x = step; x <= width; x += step) {
    d += ` L${x.toFixed(1)},${(y + amp * Math.sin((x / period) * Math.PI * 2 + phase)).toFixed(2)}`;
  }
  return d;
}

interface RankSpec {
  rows: number; amp: number; period: number;
  colour: string; strokeWidth: number; opacity: number; jitter: number;
}

export default function SeaLayer({ width, height, enabled = true }: Props) {
  // Drawn at 3x width so a one-third translate loops with no visible seam.
  const W = width * 3;

  const ranks = useMemo(() => {
    const rand = prng(20260929);
    const build = (s: RankSpec) =>
      Array.from({ length: s.rows }, (_, i) => {
        const y = (i + 0.5) * (height / s.rows) + (rand() * 2 - 1) * s.jitter;
        return {
          d: sinePath(W, y, s.amp * (0.65 + rand() * 0.8), s.period * (0.8 + rand() * 0.5), rand() * Math.PI * 2),
          o: s.opacity * (0.7 + rand() * 0.6),
        };
      });
    return {
      far: build({ rows: 16, amp: 2.6, period: 200, colour: '#4E93B4', strokeWidth: 0.9, opacity: 0.11, jitter: 10 }),
      mid: build({ rows: 13, amp: 4.0, period: 320, colour: '#63B0D2', strokeWidth: 1.1, opacity: 0.095, jitter: 14 }),
      near: build({ rows: 7, amp: 6.0, period: 480, colour: '#8FDCF5', strokeWidth: 1.4, opacity: 0.075, jitter: 18 }),
    };
  }, [W, height]);

  if (!enabled) {
    return <rect x={0} y={0} width={width} height={height} fill="var(--s-deep)" />;
  }

  return (
    <g className="sea" aria-hidden>
      <defs>
        <radialGradient id="seaDepth" cx="50%" cy="40%" r="80%">
          <stop offset="0%" stopColor="#12253A" />
          <stop offset="50%" stopColor="#0B1524" />
          <stop offset="100%" stopColor="#05080C" />
        </radialGradient>

        <pattern id="seaChop" width={52} height={30} patternUnits="userSpaceOnUse">
          <path d="M0,15 q6.5,-5.5 13,0 t13,0 t13,0 t13,0" fill="none" stroke="#6FBEDC" strokeWidth={1} strokeLinecap="round" opacity={0.55} />
          <path d="M-26,27 q6.5,-4.5 13,0 t13,0 t13,0 t13,0 t13,0" fill="none" stroke="#6FBEDC" strokeWidth={0.8} strokeLinecap="round" opacity={0.32} />
          <path d="M-13,6 q6.5,-3.5 13,0 t13,0 t13,0 t13,0 t13,0" fill="none" stroke="#6FBEDC" strokeWidth={0.6} strokeLinecap="round" opacity={0.2} />
        </pattern>

        <linearGradient id="seaSheen" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#8FDCF5" stopOpacity={0} />
          <stop offset="50%" stopColor="#8FDCF5" stopOpacity={0.10} />
          <stop offset="100%" stopColor="#8FDCF5" stopOpacity={0} />
        </linearGradient>
      </defs>

      <rect x={0} y={0} width={width} height={height} fill="url(#seaDepth)" />

      <g className="sea__chop">
        <rect x={-width} y={-40} width={W} height={height + 80} fill="url(#seaChop)" opacity={0.14} />
      </g>

      <g className="sea__swell--far">
        {ranks.far.map((r, i) => <path key={i} d={r.d} fill="none" stroke="#4E93B4" strokeWidth={0.9} opacity={r.o} />)}
      </g>
      <g className="sea__swell--mid">
        {ranks.mid.map((r, i) => <path key={i} d={r.d} fill="none" stroke="#63B0D2" strokeWidth={1.1} opacity={r.o} />)}
      </g>
      <g className="sea__swell--near">
        {ranks.near.map((r, i) => <path key={i} d={r.d} fill="none" stroke="#8FDCF5" strokeWidth={1.4} opacity={r.o} />)}
      </g>

      <g className="sea__sheen">
        <rect x={-width} y={0} width={width * 1.4} height={height} fill="url(#seaSheen)" />
      </g>
    </g>
  );
}
