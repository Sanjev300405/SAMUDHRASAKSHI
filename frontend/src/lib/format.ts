// Human-readable formatting. Nothing in the UI should print a raw enum,
// a raw MMSI digit string, or a raw ISO timestamp — route it through here.

export function vesselType(raw: string | null): string {
  if (!raw) return 'Unidentified vessel';
  return raw
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

export function mmsi(value: string | null): string {
  if (!value) return 'No MMSI';
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

export function coord(lon: number, lat: number): string {
  const ns = lat >= 0 ? 'N' : 'S';
  const ew = lon >= 0 ? 'E' : 'W';
  return `${Math.abs(lon).toFixed(3)}°${ew}  ${Math.abs(lat).toFixed(3)}°${ns}`;
}

export function durationHuman(ms: number): string {
  const abs = Math.abs(ms);
  const minutes = Math.round(abs / 60000);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'}`;
  const hours = minutes / 60;
  if (hours < 48) {
    const h = Math.round(hours * 10) / 10;
    return `${h} hour${h === 1 ? '' : 's'}`;
  }
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'}`;
}

export function titleCaseWord(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function timeOfDay(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16) + ' UTC';
}

export function dateAndTime(iso: string): string {
  const d = new Date(iso);
  return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)} UTC`;
}
