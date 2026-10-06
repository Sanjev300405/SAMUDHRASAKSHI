"""backend/api/pdf.py — a minimal, real PDF writer (stdlib only).

WeasyPrint/reportlab are not in this build's approved dependency list and
were not worth adding for a one-page text summary. This hand-writes valid
PDF 1.4 syntax (header, a handful of objects, a real xref table, trailer) —
the output is a genuine, openable PDF, not a renamed HTML/text file.
"""

from __future__ import annotations


def _escape(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _text_stream(lines: list[tuple[str, int, float]]) -> bytes:
    """lines: (text, font_size, y_position). Font F1 (Helvetica) throughout."""
    parts = ["BT"]
    for text, size, y in lines:
        parts.append(f"/F1 {size} Tf")
        parts.append(f"72 {y:.1f} Td")
        parts.append(f"({_escape(text)}) Tj")
        parts.append(f"-72 {-y:.1f} Td")  # reset to origin for the next absolute Td
    parts.append("ET")
    return ("\n".join(parts)).encode("latin-1", errors="replace")


def build_report_pdf(bundle: dict) -> bytes:
    lines: list[tuple[str, int, float]] = []
    y = 740
    lines.append((f"SAMUDRA SAKSHI -- Case Report: {bundle['case_id']}", 16, y)); y -= 24
    lines.append((f"Generated: {bundle['generated_at']}", 9, y)); y -= 24

    obs = bundle["observation"]
    lines.append(("Observation", 12, y)); y -= 16
    lines.append((f"  Area: {obs['area_km2']} km2   Classification: {obs['classification']}   Confidence: {obs['confidence']}", 10, y)); y -= 14
    lines.append((f"  Age class: {obs['age_class']}   Observed at: {obs['observed_at']}", 10, y)); y -= 24

    sources = bundle.get("source_metadata") or obs.get("source_metadata") or {}
    if sources:
        lines.append(("Input source references", 11, y)); y -= 14
        for key in ("sar", "ais", "forcing"):
            src = sources.get(key, {})
            name = str(src.get("name", "not supplied"))[:72]
            url = str(src.get("url", ""))[:76]
            lines.append((f"  {key.upper()}: {name} {url}", 8, y)); y -= 12
        y -= 8

    origin = bundle["origin"]
    lines.append(("Origin estimate", 12, y)); y -= 16
    lines.append((f"  Window: {origin['window_start']} .. {origin['window_end']}", 10, y)); y -= 14
    lines.append((f"  Ensemble size: {origin['ensemble_size']}   Spread: {origin['spread_km']} km   Forcing quality: {origin['forcing_quality']}", 10, y)); y -= 24

    lines.append(("Ranked candidates", 12, y)); y -= 16
    mmsi_by_track = {t["track_id"]: (t["mmsi"] or "no MMSI") for t in bundle["tracks"]}
    for i, c in enumerate(bundle["candidates"][:8]):
        mmsi = mmsi_by_track.get(c["track_id"], "unknown")
        lines.append((f"  {i + 1}. {c['track_id']}  {mmsi}  A={c['association']:.3f}  ({c['association_level']})", 10, y))
        y -= 14
    y -= 10

    lines.append(("Evidence-based association only. Not legal proof.", 11, y))

    stream = _text_stream(lines)

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
                    b"/MediaBox [0 0 612 792] /Contents 5 0 R >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")

    out = bytearray()
    out += b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1")
        out += obj
        out += b"\nendobj\n"

    xref_offset = len(out)
    n = len(objects) + 1
    out += f"xref\n0 {n}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("latin-1")

    return bytes(out)
