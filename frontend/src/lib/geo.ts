// Shared lon/lat -> SVG pixel projection. MapScene and SwipeComparator both
// need to place the same geometry consistently, so the projector lives here
// once rather than being duplicated per component.
import type { AISTrack, CandidateScore, OriginEstimate, SlickObservation } from './types';

export type Projector = (lon: number, lat: number) => [number, number];

/** Fixed screen-space margins (in viewBox units) to fit content INSIDE,
 * reserved for UI chrome that floats on top of the map (dock, timeline,
 * top readout band, a little breathing room). All fields default to 0 so
 * existing scalar-padding callers (SwipeComparator) are unaffected. */
export interface ContentInset {
  top: number;
  right: number;
  bottom: number;
  left: number;
}
const NO_INSET: ContentInset = { top: 0, right: 0, bottom: 0, left: 0 };

/** Bounds from whatever data has arrived so far (section C: stages reveal
 * progressively, so origin/tracks/candidates may not exist yet). `observation`
 * is the only required piece — MapScene renders nothing until Detect has
 * produced one. `origin`'s high/medium probability polygons MUST be included
 * once Trace Origin has run — they are rendered (z2/z3) and were previously
 * omitted here, which is exactly why they clipped at the map edge. */
export function boundsFromParts(parts: {
  observation: SlickObservation;
  origin?: OriginEstimate | null;
  tracks?: AISTrack[] | null;
  candidates?: CandidateScore[] | null;
}): [number, number, number, number] {
  const lons: number[] = [];
  const lats: number[] = [];
  const push = (coords: [number, number][]) => {
    for (const [lon, lat] of coords) {
      lons.push(lon);
      lats.push(lat);
    }
  };
  push(parts.observation.geometry.coordinates[0]);
  if (parts.origin) {
    push(parts.origin.high_prob_geometry.coordinates[0]);
    push(parts.origin.medium_prob_geometry.coordinates[0]);
  }
  for (const c of parts.candidates ?? []) {
    if (c.best_release) push(c.best_release.simulated_geometry.coordinates[0]);
  }
  // The incident itself -- slick, origin, simulated slicks -- defines the frame
  // we care about. Track fixes are added separately below because a full AIS
  // track can run for hundreds of km either side of the release window; folding
  // all of them in unconditionally zoomed the view out until the slick was a dot.
  const coreMinLon = Math.min(...lons);
  const coreMinLat = Math.min(...lats);
  const coreMaxLon = Math.max(...lons);
  const coreMaxLat = Math.max(...lats);

  // Only fixes inside the release window (plus a 25% margin) are relevant to
  // the incident; the rest of the voyage is not.
  const winStart = parts.origin ? Date.parse(parts.origin.window_start) : NaN;
  const winEnd = parts.origin ? Date.parse(parts.origin.window_end) : NaN;
  const hasWindow = Number.isFinite(winStart) && Number.isFinite(winEnd);
  const margin = hasWindow ? (winEnd - winStart) * 0.25 : 0;
  for (const t of parts.tracks ?? []) {
    for (const f of t.fixes) {
      if (hasWindow) {
        const ts = Date.parse(f.ts);
        if (Number.isFinite(ts) && (ts < winStart - margin || ts > winEnd + margin)) continue;
      }
      lons.push(f.lon);
      lats.push(f.lat);
    }
  }

  let minLon = Math.min(...lons);
  let minLat = Math.min(...lats);
  let maxLon = Math.max(...lons);
  let maxLat = Math.max(...lats);

  // Hard stop: never let surrounding traffic expand the view beyond 4x the
  // incident's own extent, however far a vessel wandered inside the window.
  const MAX_EXPANSION = 4;
  const coreLonSpan = Math.max(coreMaxLon - coreMinLon, 1e-6);
  const coreLatSpan = Math.max(coreMaxLat - coreMinLat, 1e-6);
  const cLon = (coreMinLon + coreMaxLon) / 2;
  const cLat = (coreMinLat + coreMaxLat) / 2;
  const capLon = (coreLonSpan * MAX_EXPANSION) / 2;
  const capLat = (coreLatSpan * MAX_EXPANSION) / 2;
  minLon = Math.max(minLon, cLon - capLon);
  maxLon = Math.min(maxLon, cLon + capLon);
  minLat = Math.max(minLat, cLat - capLat);
  maxLat = Math.min(maxLat, cLat + capLat);

  // The incident must always remain fully inside the frame.
  minLon = Math.min(minLon, coreMinLon);
  maxLon = Math.max(maxLon, coreMaxLon);
  minLat = Math.min(minLat, coreMinLat);
  maxLat = Math.max(maxLat, coreMaxLat);

  const padX = Math.max(maxLon - minLon, 1e-6) * 0.18;
  const padY = Math.max(maxLat - minLat, 1e-6) * 0.18;
  return [minLon - padX, minLat - padY, maxLon + padX, maxLat + padY];
}

function projectionParams(
  bounds: [number, number, number, number],
  width: number,
  height: number,
  paddingFrac: number,
  contentInset: ContentInset = NO_INSET,
) {
  const [minLon, minLat, maxLon, maxLat] = bounds;
  const lonSpan = Math.max(maxLon - minLon, 1e-6);
  const latSpan = Math.max(maxLat - minLat, 1e-6);
  const padX = lonSpan * paddingFrac;
  const padY = latSpan * paddingFrac;
  const lon0 = minLon - padX;
  const lon1 = maxLon + padX;
  const lat0 = minLat - padY;
  const lat1 = maxLat + padY;

  // cos(latitude) correction so degrees-lon and degrees-lat scale consistently
  const midLatRad = ((lat0 + lat1) / 2) * (Math.PI / 180);
  const cosLat = Math.max(Math.cos(midLatRad), 0.15);

  const spanX = (lon1 - lon0) * cosLat;
  const spanY = lat1 - lat0;

  // Fit into the space INSIDE the reserved margins, not the full box — this
  // is what keeps content from landing underneath the dock/timeline/readout,
  // which float on top of the map but previously weren't accounted for here.
  const innerW = Math.max(width - contentInset.left - contentInset.right, 1e-6);
  const innerH = Math.max(height - contentInset.top - contentInset.bottom, 1e-6);
  const scale = Math.min(innerW / spanX, innerH / spanY);
  const usedW = spanX * scale;
  const usedH = spanY * scale;
  const offX = contentInset.left + (innerW - usedW) / 2;
  const offY = contentInset.top + (innerH - usedH) / 2;

  return { lon0, lat1, cosLat, scale, offX, offY };
}

/** Equirectangular projection, padded, fit inside a viewBox minus contentInset. */
export function makeProjector(
  bounds: [number, number, number, number],
  width: number,
  height: number,
  paddingFrac = 0.12,
  contentInset: ContentInset = NO_INSET,
): Projector {
  const { lon0, lat1, cosLat, scale, offX, offY } = projectionParams(bounds, width, height, paddingFrac, contentInset);
  return (lon, lat) => {
    const x = offX + (lon - lon0) * cosLat * scale;
    const y = offY + (lat1 - lat) * scale;
    return [x, y];
  };
}

/** Inverse of makeProjector — screen/viewBox pixel back to lon/lat. Must be
 * called with the same bounds/width/height/paddingFrac/contentInset as the
 * forward projector. */
export function makeUnprojector(
  bounds: [number, number, number, number],
  width: number,
  height: number,
  paddingFrac = 0.12,
  contentInset: ContentInset = NO_INSET,
): (x: number, y: number) => [number, number] {
  const { lon0, lat1, cosLat, scale, offX, offY } = projectionParams(bounds, width, height, paddingFrac, contentInset);
  return (x, y) => {
    const lon = lon0 + (x - offX) / (cosLat * scale);
    const lat = lat1 - (y - offY) / scale;
    return [lon, lat];
  };
}

/** viewBox units per kilometre at the projection's reference latitude —
 * used to size a scale bar. Must share contentInset with the projector it
 * describes, or the bar would report a distance for a different fit. */
export function unitsPerKm(
  bounds: [number, number, number, number],
  width: number,
  height: number,
  paddingFrac: number,
  contentInset: ContentInset = NO_INSET,
): number {
  const project = makeProjector(bounds, width, height, paddingFrac, contentInset);
  const [, lat0] = bounds;
  const [x0, y0] = project(bounds[0], lat0);
  const oneKmLatDeg = 1 / 111.32;
  const [x1, y1] = project(bounds[0], lat0 + oneKmLatDeg);
  return Math.hypot(x1 - x0, y1 - y0);
}

/** Largest/smallest of {1,2,5}×10^n relative to x — used for scale-bar
 * distances and graticule steps so labels land on round numbers. */
export function niceNumber(x: number, roundUp: boolean): number {
  if (!(x > 0)) return 0;
  const exp = Math.floor(Math.log10(x));
  const base = Math.pow(10, exp);
  const frac = x / base;
  let niceFrac: number;
  if (roundUp) {
    niceFrac = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10;
  } else {
    niceFrac = frac >= 5 ? 5 : frac >= 2 ? 2 : 1;
  }
  return niceFrac * base;
}

export function projectRing(ring: [number, number][], project: Projector): string {
  return ring.map(([lon, lat]) => project(lon, lat).join(',')).join(' ');
}
