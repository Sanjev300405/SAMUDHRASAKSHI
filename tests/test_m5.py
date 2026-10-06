"""ARCHITECTURE.md §5 M5: "Missing AIS is a data-quality flag, never evidence
of wrongdoing. Enforced in code (Q only ever lowers confidence...)."

This test constructs the SAME track twice, then removes fixes from the
second copy to simulate additional gaps, and asserts the score can only go
down (or stay equal), never up.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.core.m5_ais_recon import track_quality


def _make_fixes(n: int, interval_min: float = 20.0, start=None):
    start = start or datetime(2030, 1, 1, 0, 0, 0)
    fixes = []
    for i in range(n):
        t = start + timedelta(minutes=i * interval_min)
        fixes.append({
            "ts": t.isoformat(), "lon": 63.0 + i * 0.001, "lat": 19.5 + i * 0.001,
            "sog": 8.0, "cog": 45.0, "heading": 45.0,
        })
    return fixes


def test_more_gaps_never_scores_higher():
    full = _make_fixes(30)
    q_full = track_quality(full, max_speed_kn=25.0)["score"]

    for n_removed in (2, 5, 10, 15, 20):
        # drop a contiguous interior slice to guarantee strictly fewer fixes
        # present, i.e. strictly more gap, than the full track
        gappy = full[:1] + full[1 + n_removed:]
        q_gappy = track_quality(gappy, max_speed_kn=25.0)["score"]
        assert q_gappy <= q_full, (
            f"track with {n_removed} more gaps scored {q_gappy} > full track's {q_full}"
        )


def test_gap_fraction_monotonic_pairwise():
    full = _make_fixes(40)
    prev_score = 1.0
    for n_removed in (0, 4, 8, 12, 16, 20, 24):
        gappy = full[:1] + full[1 + n_removed:] if n_removed else full
        result = track_quality(gappy, max_speed_kn=25.0)
        assert result["score"] <= prev_score + 1e-9, (
            f"score increased after removing {n_removed} fixes: "
            f"{result['score']} > {prev_score}"
        )
        prev_score = result["score"]


def test_quality_never_exceeds_bounds():
    for n in (2, 5, 10, 25, 50):
        fixes = _make_fixes(n)
        q = track_quality(fixes, max_speed_kn=25.0)["score"]
        assert 0.2 <= q <= 1.0
