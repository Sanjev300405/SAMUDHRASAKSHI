import { useEffect, useMemo, useRef, useState } from 'react';
import type { AISTrack, CandidateScore, OriginEstimate, SlickObservation } from '../lib/types';
import SeaLayer from './SeaLayer';
import { boundsFromParts, makeProjector, makeUnprojector, niceNumber, projectRing, unitsPerKm, type ContentInset } from '../lib/geo';
import { coord, mmsi as fmtMmsi } from '../lib/format';

const BASE_H = 700;

/* Set to false to render a flat ocean instead of the animated one. */
const SEA_ANIMATED = true;
const VESSEL_LABEL_LIMIT = 12;
const MIN_K = 0.5;
const MAX_K = 20;

interface Transform { k: number; tx: number; ty: number }
const IDENTITY: Transform = { k: 1, tx: 0, ty: 0 };

interface Props {
  observation: SlickObservation | null;
  origin: OriginEstimate | null;
  tracks: AISTrack[] | null;
  candidates: CandidateScore[] | null;
  selectedTrackId: string | null;
  playheadMs: number | null;
  onSelectVessel?: (trackId: string) => void;
  showOrigin: boolean;
  showTraffic: boolean;
  showSimulated: boolean;
}

function interpolateFix(track: AISTrack, atMs: number) {
  const fixes = track.fixes;
  if (fixes.length === 0) return null;
  const times = fixes.map((f) => Date.parse(f.ts));
  if (atMs <= times[0]) return fixes[0];
  if (atMs >= times[times.length - 1]) return fixes[fixes.length - 1];
  for (let i = 0; i < times.length - 1; i++) {
    if (atMs >= times[i] && atMs <= times[i + 1]) {
      const span = times[i + 1] - times[i];
      const t = span === 0 ? 0 : (atMs - times[i]) / span;
      const a = fixes[i];
      const b = fixes[i + 1];
      return {
        ts: new Date(atMs).toISOString(),
        lon: a.lon + (b.lon - a.lon) * t,
        lat: a.lat + (b.lat - a.lat) * t,
        sog: a.sog + (b.sog - a.sog) * t,
        cog: a.cog + (b.cog - a.cog) * t,
        heading: a.heading + (b.heading - a.heading) * t,
      };
    }
  }
  return fixes[fixes.length - 1];
}

function easeInOutQuad(t: number): number {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

export default function MapScene({ observation, origin, tracks, candidates, selectedTrackId, playheadMs, onSelectVessel, showOrigin, showTraffic, showSimulated }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  // MapScene early-returns an empty state (below) until `observation` exists,
  // so the real <svg ref={svgRef}> doesn't mount on the first render or two —
  // svgRef.current is null then. A plain `useRef` gives no signal for when
  // that later changes, so an effect keyed only on [VB_W, VB_H] would attach
  // its listener against a null ref once and never retry once the element
  // actually appears (VB_W/VB_H don't necessarily change at that moment).
  // This state mirrors the ref and DOES change on mount, giving the wheel
  // effect below a real dependency to re-fire on.
  const [svgMounted, setSvgMounted] = useState(false);
  const [size, setSize] = useState({ w: 1000, h: 700 });
  const [hover, setHover] = useState<[number, number] | null>(null);
  const [transform, setTransform] = useState<Transform>(IDENTITY);
  const dragRef = useRef<{ vx: number; vy: number } | null>(null);
  const animRef = useRef<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const VB_H = BASE_H;
  const VB_W = BASE_H * (size.w / size.h);

  const cssPx = (name: string, fallback: number) => {
    const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name));
    return Number.isFinite(v) && v > 0 ? v : fallback;
  };
  const timelineInsetVB = (cssPx('--timeline-h', 72) / size.h) * VB_H;
  const dockInsetVB = (cssPx('--dock-w', 380) / size.w) * VB_W;
  const topBandVB = (cssPx('--top-band-h', 110) / size.h) * VB_H;
  const legendKeepoutWpx = 300;
  const legendKeepoutHpx = 300;
  const legendKeepoutWVB = (legendKeepoutWpx / size.w) * VB_W;
  const legendKeepoutHVB = (legendKeepoutHpx / size.h) * VB_H;

  // Fix B: fit content into the RECTANGLE STILL VISIBLE under the floating
  // chrome (dock right, timeline bottom, readout/chips top), not the full
  // SVG box — this is what was landing geometry underneath them before.
  const contentInset: ContentInset = useMemo(() => ({
    top: topBandVB + 24,
    right: dockInsetVB + 24,
    bottom: timelineInsetVB + 24,
    left: 24,
  }), [topBandVB, dockInsetVB, timelineInsetVB]);

  const effectiveOrigin = showOrigin ? origin : null;
  const effectiveTracks = showTraffic ? tracks : null;
  const effectiveCandidates = showSimulated ? candidates : null;

  // Fix A: origin's high/medium polygons are rendered (z2/z3) and must be
  // included when fitting bounds, or they draw outside the fit and clip.
  const bounds = useMemo(
    () => (observation ? boundsFromParts({ observation, origin: effectiveOrigin, tracks: effectiveTracks, candidates: effectiveCandidates }) : null),
    [observation, effectiveOrigin, effectiveTracks, effectiveCandidates],
  );
  const project = useMemo(() => (bounds ? makeProjector(bounds, VB_W, VB_H, 0, contentInset) : null), [bounds, VB_W, VB_H, contentInset]);
  const unproject = useMemo(() => (bounds ? makeUnprojector(bounds, VB_W, VB_H, 0, contentInset) : null), [bounds, VB_W, VB_H, contentInset]);

  // A newly-revealed stage refits its own bounds (via the memo above) — snap
  // the interactive zoom/pan back to that fresh fit rather than keeping a
  // stale transform computed against the old, smaller bounds.
  useEffect(() => { setTransform(IDENTITY); }, [bounds]);

  // Fix D: a dev-only guard that would have caught bug 1 immediately — warns
  // by name if any rendered layer's geometry falls outside the fitted bounds.
  useEffect(() => {
    if (!import.meta.env.DEV || !bounds || !observation) return;
    const [minLon, minLat, maxLon, maxLat] = bounds;
    const within = (lon: number, lat: number) => lon >= minLon && lon <= maxLon && lat >= minLat && lat <= maxLat;
    const checkRing = (name: string, ring: [number, number][]) => {
      if (ring.some(([lon, lat]) => !within(lon, lat))) {
        console.warn(`[MapScene] layer "${name}" has geometry outside the fitted bounds — it will render clipped. Fix boundsFromParts() or the bounds memo's dependencies.`);
      }
    };
    checkRing('observed slick', observation.geometry.coordinates[0]);
    if (effectiveOrigin) {
      checkRing('origin high-probability', effectiveOrigin.high_prob_geometry.coordinates[0]);
      checkRing('origin medium-probability', effectiveOrigin.medium_prob_geometry.coordinates[0]);
    }
    for (const t of effectiveTracks ?? []) {
      if (t.fixes.some((f) => !within(f.lon, f.lat))) {
        console.warn(`[MapScene] track "${t.track_id}" has a fix outside the fitted bounds — it will render clipped.`);
      }
    }
    for (const c of effectiveCandidates ?? []) {
      if (c.best_release) checkRing(`simulated slick (${c.track_id})`, c.best_release.simulated_geometry.coordinates[0]);
    }
  }, [bounds, observation, effectiveOrigin, effectiveTracks, effectiveCandidates]);

  // Declared above the early return below, because the vessel-marker memo that
  // follows is a hook and must run on every render regardless of whether the
  // observation has arrived yet.
  const ph = playheadMs ?? (observation ? Date.parse(observation.observed_at) : Number.NaN);


  /* Vessel marker positions with vertical label de-collision. Labels are
     pushed apart along y (in viewBox units) so two vessels sitting close
     together no longer print their MMSI on top of each other. */
  const vesselMarks = useMemo(() => {
    if (!project || !effectiveTracks) return [];
    const marks = effectiveTracks.flatMap((t) => {
      const fix = interpolateFix(t, ph);
      if (!fix) return [];
      const [x, y] = project(fix.lon, fix.lat);
      const isDark = t.mmsi === null;
      const isSelected = selectedTrackId === t.track_id;
      return [{
        trackId: t.track_id,
        mmsi: t.mmsi,
        x, y,
        labelY: y + 3 / transform.k,
        heading: fix.heading,
        isSelected,
        color: isDark ? 'var(--dark-vessel)' : isSelected ? 'var(--track-sel)' : 'var(--track)',
      }];
    });
    const minGap = 11 / transform.k;
    const byColumn = new Map<number, typeof marks>();
    for (const m of marks) {
      const col = Math.round(m.x / (70 / transform.k));
      const arr = byColumn.get(col) ?? [];
      arr.push(m);
      byColumn.set(col, arr);
    }
    for (const arr of byColumn.values()) {
      arr.sort((a, b) => a.labelY - b.labelY);
      for (let i = 1; i < arr.length; i++) {
        if (arr[i].labelY - arr[i - 1].labelY < minGap) {
          arr[i].labelY = arr[i - 1].labelY + minGap;
        }
      }
    }
    return marks;
  }, [project, effectiveTracks, ph, selectedTrackId, transform.k]);

  const selectedCandidate = effectiveCandidates?.find((c) => c.track_id === selectedTrackId) ?? null;

  const graticule = useMemo(() => {
    if (!bounds || !project) return null;
    const [minLon, minLat, maxLon, maxLat] = bounds;
    const lonStep = niceNumber((maxLon - minLon) / 5, true);
    const latStep = niceNumber((maxLat - minLat) / 4, true);
    const decimals = (step: number) => (step >= 1 ? 0 : step >= 0.1 ? 1 : step >= 0.01 ? 2 : 3);

    const vLines: { x: number; lon: number }[] = [];
    for (let lon = Math.ceil(minLon / lonStep) * lonStep; lon <= maxLon; lon += lonStep) {
      vLines.push({ x: project(lon, minLat)[0], lon });
    }
    const hLines: { y: number; lat: number }[] = [];
    for (let lat = Math.ceil(minLat / latStep) * latStep; lat <= maxLat; lat += latStep) {
      hLines.push({ y: project(minLon, lat)[1], lat });
    }
    return { vLines, hLines, lonDecimals: decimals(lonStep), latDecimals: decimals(latStep) };
  }, [bounds, project]);

  // Fix C: the scale bar must read the SAME {k,tx,ty} transform the content
  // group uses, not the untransformed projector — a fixed on-screen length
  // represents fewer km as you zoom in.
  const scaleBar = useMemo(() => {
    if (!bounds) return null;
    const upk = unitsPerKm(bounds, VB_W, VB_H, 0, contentInset) * transform.k;
    const targetPx = VB_W * 0.12;
    const km = niceNumber(targetPx / upk, false) || 1;
    return { km, px: km * upk };
  }, [bounds, VB_W, VB_H, contentInset, transform.k]);

  const showVesselLabels = (effectiveTracks?.length ?? 0) <= VESSEL_LABEL_LIMIT;

  const screenToVB = (clientX: number, clientY: number): [number, number] => {
    const rect = svgRef.current!.getBoundingClientRect();
    return [((clientX - rect.left) / rect.width) * VB_W, ((clientY - rect.top) / rect.height) * VB_H];
  };

  const stopAnim = () => {
    if (animRef.current !== null) { cancelAnimationFrame(animRef.current); animRef.current = null; }
  };

  const animateTo = (target: Transform, duration = 200) => {
    stopAnim();
    const start = performance.now();
    const from = transform;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const e = easeInOutQuad(t);
      setTransform({
        k: from.k + (target.k - from.k) * e,
        tx: from.tx + (target.tx - from.tx) * e,
        ty: from.ty + (target.ty - from.ty) * e,
      });
      animRef.current = t < 1 ? requestAnimationFrame(step) : null;
    };
    animRef.current = requestAnimationFrame(step);
  };

  const handleFit = () => animateTo(IDENTITY, 200);

  // React's synthetic onWheel is attached as a passive listener (for scroll
  // perf), so calling preventDefault() inside it throws "Unable to
  // preventDefault inside passive event listener invocation." — a real,
  // console-visible error. A native listener with {passive:false} is the
  // documented way around that; setTransform's functional updater means this
  // doesn't need `transform` in its closure, so re-subscribing only on
  // VB_W/VB_H changes (a resize) is enough to stay correct.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheelNative = (e: WheelEvent) => {
      e.preventDefault();
      stopAnim();
      const [mx, my] = screenToVB(e.clientX, e.clientY);
      const factor = Math.exp(-e.deltaY * 0.0015);
      setTransform((prev) => {
        const newK = Math.min(MAX_K, Math.max(MIN_K, prev.k * factor));
        const worldX = (mx - prev.tx) / prev.k;
        const worldY = (my - prev.ty) / prev.k;
        return { k: newK, tx: mx - newK * worldX, ty: my - newK * worldY };
      });
    };
    svg.addEventListener('wheel', onWheelNative, { passive: false });
    return () => svg.removeEventListener('wheel', onWheelNative);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [svgMounted, VB_W, VB_H]);

  const handlePointerDown: React.PointerEventHandler<SVGSVGElement> = (e) => {
    if (!svgRef.current) return;
    stopAnim();
    const [vx, vy] = screenToVB(e.clientX, e.clientY);
    dragRef.current = { vx, vy };
    (e.target as Element).setPointerCapture(e.pointerId);
  };
  const handlePointerUp = () => { dragRef.current = null; };

  const handlePointerMove: React.PointerEventHandler<SVGSVGElement> = (e) => {
    if (!svgRef.current) return;
    const [vx, vy] = screenToVB(e.clientX, e.clientY);
    if (dragRef.current) {
      const dx = vx - dragRef.current.vx;
      const dy = vy - dragRef.current.vy;
      dragRef.current = { vx, vy };
      setTransform((prev) => ({ ...prev, tx: prev.tx + dx, ty: prev.ty + dy }));
    }
    if (unproject) {
      const worldX = (vx - transform.tx) / transform.k;
      const worldY = (vy - transform.ty) / transform.k;
      setHover(unproject(worldX, worldY));
    }
  };

  if (!observation || !bounds || !project) {
    return (
      <div className="map-scene-wrap map-scene-wrap--empty" ref={wrapRef}>
        <div className="panel-state panel-state--idle">Run Detect to see the scene.</div>
      </div>
    );
  }

  const contentTransform = `translate(${transform.tx},${transform.ty}) scale(${transform.k})`;

  return (
    <div className="map-scene-wrap" ref={wrapRef}>
      <svg
        ref={(el) => { svgRef.current = el; setSvgMounted(!!el); }}
        className="map-scene"
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Case map"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={() => { handlePointerUp(); setHover(null); }}
        style={{ cursor: dragRef.current ? 'grabbing' : 'grab' }}
      >
        {/* z0 — basemap, fixed (does not pan/zoom with content) */}
        {/* z-1 — animated open ocean. Screen space, outside the pan/zoom
            transform: water is a surface, not a texture on the seabed. */}
        <SeaLayer width={VB_W} height={VB_H} enabled={SEA_ANIMATED} />

        {/* everything below is real map content: pans and zooms together */}
        <g transform={contentTransform}>
          {graticule?.vLines.map((l) => (
            <line key={`v${l.lon}`} x1={l.x} y1={0} x2={l.x} y2={VB_H} stroke="var(--s-line)" strokeWidth={1 / transform.k} opacity={0.5} />
          ))}
          {graticule?.hLines.map((l) => (
            <line key={`h${l.lat}`} x1={0} y1={l.y} x2={VB_W} y2={l.y} stroke="var(--s-line)" strokeWidth={1 / transform.k} opacity={0.5} />
          ))}

          {/* z1 — SAR scene footprint (synthetic; no raster asset in this prototype) */}
          <rect
            x={VB_W * 0.06} y={VB_H * 0.06} width={VB_W * 0.88} height={VB_H * 0.88}
            fill="url(#sarHatch)" opacity={0.35}
          />

          {/* z2/z3 — origin probability map + contours (Trace Origin stage).
              layer-fade-in: section B (previous prompt) — 200ms fade on arrival. */}
          {showOrigin && origin && (
            <g className="layer-fade-in" key={`origin-${origin.window_start}`}>
              <polygon points={projectRing(origin.medium_prob_geometry.coordinates[0], project)} fill="var(--origin-lo)" opacity={0.16} />
              <polygon points={projectRing(origin.high_prob_geometry.coordinates[0], project)} fill="var(--origin-hi)" opacity={0.22} />
              <polygon points={projectRing(origin.medium_prob_geometry.coordinates[0], project)} fill="none" stroke="var(--origin-md)" strokeWidth={1.5 / transform.k} strokeDasharray="4 3" />
              <polygon points={projectRing(origin.high_prob_geometry.coordinates[0], project)} fill="none" stroke="var(--origin-hi)" strokeWidth={1.5 / transform.k} />
            </g>
          )}

          {/* z4 — AIS tracks, animated to the scrubber (Analyse Traffic stage) */}
          {effectiveTracks && (
            <g className="layer-fade-in" key={`tracks-${effectiveTracks.length}`}>
              {effectiveTracks.map((t) => {
                const pts = t.fixes
                  .filter((f) => Date.parse(f.ts) <= ph)
                  .map((f) => project(f.lon, f.lat).join(','))
                  .join(' ');
                const isSelected = selectedTrackId === t.track_id;
                return (
                  <polyline
                    key={t.track_id}
                    points={pts}
                    fill="none"
                    stroke={isSelected ? 'var(--track-sel)' : 'var(--track)'}
                    strokeWidth={(isSelected ? 2 : 1.5) / transform.k}
                    opacity={isSelected ? 0.95 : 0.55}
                  />
                );
              })}
            </g>
          )}

          {/* z5 — simulated slick (M6), Run Simulation stage */}
          {showSimulated && selectedCandidate?.best_release && (
            <g className="layer-fade-in" key={`sim-${selectedCandidate.candidate_id}`}>
              <polygon
                points={projectRing(selectedCandidate.best_release.simulated_geometry.coordinates[0], project)}
                fill="var(--sim)" fillOpacity={0.35} stroke="var(--sim)" strokeWidth={2 / transform.k}
              />
            </g>
          )}

          {/* z6 — observed slick, always on top of the simulated layer, from Detect onward */}
          <polygon
            points={projectRing(observation.geometry.coordinates[0], project)}
            fill="var(--slick)" fillOpacity={0.28} stroke="var(--slick)" strokeWidth={2.5 / transform.k}
          />

          {/* z7 — vessels, drawn as a top-down ship silhouette rotated to true
              heading. Labels are de-collided vertically: two vessels close
              together previously stacked their MMSI text on the same line. */}
          {vesselMarks.map((m) => (
            <g key={m.trackId}>
              <g
                transform={`translate(${m.x},${m.y}) rotate(${m.heading}) scale(${1 / transform.k})`}
                style={{ cursor: 'pointer' }}
                onClick={() => onSelectVessel?.(m.trackId)}
              >
                {/* hull: pointed bow at -y, parallel sides, square stern */}
                <path
                  d="M0,-10 L3.6,-4.6 L3.6,7.4 L-3.6,7.4 L-3.6,-4.6 Z"
                  fill={m.color}
                  stroke="var(--s-void)"
                  strokeWidth={1}
                  strokeLinejoin="round"
                />
                {/* superstructure block, aft of midships */}
                <rect x={-1.9} y={-1.4} width={3.8} height={5.2} rx={0.6} fill="var(--s-void)" opacity={0.5} />
                {m.isSelected && (
                  <path
                    d="M0,-10 L3.6,-4.6 L3.6,7.4 L-3.6,7.4 L-3.6,-4.6 Z"
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth={1.4}
                  />
                )}
              </g>
              {showVesselLabels && (
                <>
                  {Math.abs(m.labelY - m.y) > 0.5 / transform.k && (
                    <line
                      x1={m.x + 5 / transform.k}
                      y1={m.y}
                      x2={m.x + 10 / transform.k}
                      y2={m.labelY - 2.5 / transform.k}
                      stroke="var(--s-line)"
                      strokeWidth={1 / transform.k}
                    />
                  )}
                  <text
                    x={m.x + 12 / transform.k}
                    y={m.labelY}
                    className="num vessel-label"
                    stroke="var(--s-void)"
                    strokeWidth={3 / transform.k}
                    paintOrder="stroke"
                    fill={m.isSelected ? 'var(--fg-primary)' : 'var(--fg-secondary)'}
                    style={{ fontSize: 9 / transform.k }}
                  >
                    {fmtMmsi(m.mmsi)}
                  </text>
                </>
              )}
            </g>
          ))}

          {/* z8 — selection pulse */}
          {effectiveTracks && selectedTrackId && (() => {
            const t = effectiveTracks.find((tr) => tr.track_id === selectedTrackId);
            const fix = t ? interpolateFix(t, ph) : null;
            if (!fix) return null;
            const [x, y] = project(fix.lon, fix.lat);
            return (
              <circle cx={x} cy={y} r={12 / transform.k} fill="none" stroke="var(--accent)" strokeWidth={1.5 / transform.k} className="selection-pulse" />
            );
          })()}

          {/* graticule coordinate labels — follow the same transform as the
              lines they annotate (section C: "must follow the transform too") */}
          {graticule?.vLines.map((l) => {
            const inDock = l.x > VB_W - dockInsetVB - 20;
            const inLegend = l.x < legendKeepoutWVB;
            if (inDock || inLegend) return null;
            return (
              <text key={`vl${l.lon}`} x={l.x + 3 / transform.k} y={VB_H - timelineInsetVB - 6} className="num graticule-label" style={{ fontSize: 9 / transform.k }}>
                {Math.abs(l.lon).toFixed(graticule.lonDecimals)}&deg;{l.lon >= 0 ? 'E' : 'W'}
              </text>
            );
          })}
          {graticule?.hLines.map((l) => {
            const inLegend = l.y > VB_H - legendKeepoutHVB;
            if (inLegend) return null;
            return (
              <text key={`hl${l.lat}`} x={4} y={l.y - 3 / transform.k} className="num graticule-label" style={{ fontSize: 9 / transform.k }}>
                {Math.abs(l.lat).toFixed(graticule.latDecimals)}&deg;{l.lat >= 0 ? 'N' : 'S'}
              </text>
            );
          })}
        </g>

        {/* fixed UI chrome — never pans/zooms, but its VALUES (scale bar km,
            hover lon/lat) are computed from the live transform above */}
        {scaleBar && (
          <>
            <g transform={`translate(${VB_W - dockInsetVB - 40}, ${VB_H - timelineInsetVB - 62})`}>
              <line x1={0} y1={14} x2={0} y2={0} stroke="var(--fg-tertiary)" strokeWidth={1.5} markerEnd="url(#northHead)" />
              <text x={0} y={26} textAnchor="middle" className="num graticule-label">N</text>
            </g>
            <g transform={`translate(${VB_W - dockInsetVB - 16 - scaleBar.px}, ${VB_H - timelineInsetVB - 16})`}>
              <line x1={0} y1={0} x2={scaleBar.px} y2={0} stroke="var(--fg-tertiary)" strokeWidth={1.5} />
              <line x1={0} y1={-4} x2={0} y2={4} stroke="var(--fg-tertiary)" strokeWidth={1.5} />
              <line x1={scaleBar.px} y1={-4} x2={scaleBar.px} y2={4} stroke="var(--fg-tertiary)" strokeWidth={1.5} />
              <text x={scaleBar.px / 2} y={-8} textAnchor="middle" className="num graticule-label">{scaleBar.km} km</text>
            </g>
          </>
        )}

        <defs>
          <pattern id="sarHatch" width={10} height={10} patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <line x1={0} y1={0} x2={0} y2={10} stroke="var(--fg-tertiary)" strokeWidth={1} opacity={0.5} />
          </pattern>
          <marker id="northHead" markerWidth={8} markerHeight={8} refX={3} refY={3} orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="var(--fg-tertiary)" />
          </marker>
        </defs>
      </svg>

      <button className="map-fit-btn" onClick={handleFit} title="Reset zoom and pan to fit all visible layers">
        <svg width="14" height="14" viewBox="0 0 24 24">
          <path d="M4 9 V5 a1 1 0 0 1 1-1 H9 M15 4 H19 a1 1 0 0 1 1 1 V9 M20 15 V19 a1 1 0 0 1-1 1 H15 M9 20 H5 a1 1 0 0 1-1-1 V15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        Fit
      </button>

      {hover && (
        <div className="map-hover-chip num">{coord(hover[0], hover[1])}</div>
      )}
    </div>
  );
}
