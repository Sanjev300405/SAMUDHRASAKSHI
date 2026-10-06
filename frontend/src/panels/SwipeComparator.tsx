import { useMemo, useRef, useState } from 'react';
import type { CandidateScore, GeoJSONPolygon } from '../lib/types';
import { makeProjector, projectRing } from '../lib/geo';

const VB_W = 640;
const VB_H = 360;

interface Props {
  candidate: CandidateScore;
  observedGeometry: GeoJSONPolygon;
}

function centroid(ring: [number, number][]): [number, number] {
  let sx = 0;
  let sy = 0;
  for (const [lon, lat] of ring) {
    sx += lon;
    sy += lat;
  }
  return [sx / ring.length, sy / ring.length];
}

/** Rough great-circle distance in km, good enough for a readout label. */
function kmBetween(a: [number, number], b: [number, number]): number {
  const midLat = ((a[1] + b[1]) / 2) * (Math.PI / 180);
  const dx = (b[0] - a[0]) * Math.cos(midLat) * 111.32;
  const dy = (b[1] - a[1]) * 111.32;
  return Math.hypot(dx, dy);
}

export default function SwipeComparator({ candidate, observedGeometry }: Props) {
  const [pct, setPct] = useState(50);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const release = candidate.best_release;
  const obsRing = observedGeometry.coordinates[0];
  const simRing = release?.simulated_geometry.coordinates[0] ?? null;

  // Frame the OBSERVED slick, always. Fitting both shapes meant that when the
  // counterfactual landed far away (hit-rate 0) the scale collapsed and both
  // slicks rendered as dots. The simulated slick is drawn when it falls inside
  // this frame, and reported as an off-view bearing when it does not.
  const bounds = useMemo(() => {
    const lons = obsRing.map((c) => c[0]);
    const lats = obsRing.map((c) => c[1]);
    return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)] as
      [number, number, number, number];
  }, [obsRing]);

  const project = useMemo(() => makeProjector(bounds, VB_W, VB_H, 0.35), [bounds]);

  const simOffView = useMemo(() => {
    if (!simRing) return null;
    const c = centroid(simRing);
    const [sx, sy] = project(c[0], c[1]);
    const inside = sx >= 0 && sx <= VB_W && sy >= 0 && sy <= VB_H;
    if (inside) return null;
    const obsC = centroid(obsRing);
    const [ox, oy] = project(obsC[0], obsC[1]);
    const ang = Math.atan2(sy - oy, sx - ox);
    const r = Math.min(VB_W, VB_H) * 0.38;
    return {
      x: ox + Math.cos(ang) * r,
      y: oy + Math.sin(ang) * r,
      deg: (ang * 180) / Math.PI,
      km: kmBetween(obsC, c),
    };
  }, [simRing, obsRing, project]);

  const updateFromClientX = (clientX: number) => {
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const frac = (clientX - rect.left) / rect.width;
    setPct(Math.min(100, Math.max(0, frac * 100)));
  };

  if (!release || !simRing) {
    return (
      <div className="panel swipe-comparator swipe-comparator--empty">
        No counterfactual release point was found for this vessel.
      </div>
    );
  }

  const noOverlap = release.hit_rate <= 0 && release.iou <= 0;

  return (
    <div
      className="panel e3 swipe-comparator"
      ref={containerRef}
      onPointerDown={(e) => { dragging.current = true; (e.target as Element).setPointerCapture(e.pointerId); updateFromClientX(e.clientX); }}
      onPointerMove={(e) => { if (dragging.current) updateFromClientX(e.clientX); }}
      onPointerUp={() => { dragging.current = false; }}
    >
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="swipe-comparator__svg">
        <rect x={0} y={0} width={VB_W} height={VB_H} fill="var(--s-deep)" />

        {/* observed slick — full width, base layer */}
        <polygon points={projectRing(obsRing, project)} fill="var(--slick)" fillOpacity={0.32} stroke="var(--slick)" strokeWidth={2.5} />

        {/* simulated slick — clipped to the left of the divider */}
        {!simOffView && (
          <g clipPath={`inset(0 ${100 - pct}% 0 0)`}>
            <polygon points={projectRing(simRing, project)} fill="var(--sim)" fillOpacity={0.4} stroke="var(--sim)" strokeWidth={2} />
          </g>
        )}

        {/* simulated slick fell outside this frame — show where it went */}
        {simOffView && (
          <g>
            <g transform={`translate(${simOffView.x},${simOffView.y}) rotate(${simOffView.deg})`}>
              <path d="M-14,-7 L4,0 L-14,7 Z" fill="var(--sim)" opacity={0.9} />
            </g>
            <text
              x={simOffView.x}
              y={simOffView.y + 20}
              textAnchor="middle"
              className="num"
              fill="var(--sim)"
              stroke="var(--s-void)"
              strokeWidth={3}
              paintOrder="stroke"
              style={{ fontSize: 13 }}
            >
              {`simulated slick ${simOffView.km.toFixed(1)} km away`}
            </text>
          </g>
        )}

        {!simOffView && (
          <line x1={(pct / 100) * VB_W} y1={0} x2={(pct / 100) * VB_W} y2={VB_H} stroke="var(--fg-primary)" strokeWidth={1.5} opacity={0.8} />
        )}
      </svg>

      {!simOffView && <div className="swipe-comparator__handle" style={{ left: `${pct}%` }} aria-hidden />}

      <div
        className="swipe-comparator__readout num"
        style={simOffView ? { left: '50%' } : { left: `${pct}%` }}
      >
        hit-rate {(release.hit_rate * 100).toFixed(0)}% &middot; IoU {release.iou.toFixed(2)}
      </div>

      {noOverlap && (
        <div className="swipe-comparator__verdict">
          This vessel&rsquo;s oil would not have reached the observed slick.
        </div>
      )}

      <div className="swipe-comparator__labels">
        <span className="label" style={{ color: 'var(--sim)' }}>SIMULATED</span>
        <span className="label" style={{ color: 'var(--slick)' }}>OBSERVED</span>
      </div>
    </div>
  );
}
