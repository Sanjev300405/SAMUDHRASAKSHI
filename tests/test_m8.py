"""ARCHITECTURE.md §5 M8: "Scores and explanations are produced in the same
pass" -- sum(Evidence.weight_contribution) must equal CandidateScore.association
to within 1e-9. Exercised against the real pipeline chain (M3->M4->M5->M6->M7->M8)
over the checked-in demo case, not toy inputs, so the invariant is verified
against the actual numbers that ship in bundle.json.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from backend.adapters.forcing import uniform_forcing
from backend.core.m3_characterise import load_observation
from backend.core.m4_hindcast import run_hindcast
from backend.core.m5_ais_recon import reconstruct
from backend.core.m6_counterfactual import run_counterfactual
from backend.core.m7_behaviour import behaviour_score
from backend.core.m8_fusion import fuse_candidate, load_weights
from synth.make_case import make_case

CASE_DIR = Path("cases/_test_m8")


@pytest.fixture(scope="module")
def pipeline_candidates():
    make_case(case_id="_test_m8", seed=7, n_distractors=3, out=CASE_DIR, n_particles=150)
    obs = load_observation(CASE_DIR)
    forcing = uniform_forcing()
    origin = run_hindcast(obs, forcing, ensemble=6, particles=100, seed=3)
    origin_cloud = origin.pop("_origin_cloud")

    import json
    raw_tracks = json.loads((CASE_DIR / "raw" / "ais_feed.json").read_text())
    candidates = reconstruct(raw_tracks, origin)
    assert candidates, "expected at least one candidate to survive M5 filtering"

    m6_results = run_counterfactual(
        candidates,
        datetime.fromisoformat(origin["window_start"]),
        datetime.fromisoformat(origin["window_end"]),
        datetime.fromisoformat(obs["observed_at"]),
        obs["geometry"],
        forcing,
        particles_per_release=40,
    )
    weights_cfg = load_weights("config/weights.yaml")
    rng = np.random.default_rng(11)

    fused = []
    for cand in candidates:
        beh = behaviour_score(
            cand["fixes"],
            datetime.fromisoformat(origin["window_start"]),
            datetime.fromisoformat(origin["window_end"]),
        )
        fused.append(fuse_candidate(
            cand, m6_results[cand["track_id"]], beh, origin_cloud, obs["geometry"],
            obs["orientation_deg"], datetime.fromisoformat(origin["window_start"]),
            datetime.fromisoformat(origin["window_end"]), origin["forcing_quality"],
            weights_cfg, rng,
        ))
    return fused


def test_evidence_sums_to_association(pipeline_candidates):
    assert len(pipeline_candidates) > 0
    for c in pipeline_candidates:
        total = sum(e["weight_contribution"] for e in c["evidence"])
        assert abs(total - c["association"]) < 1e-9, (
            f"{c['track_id']}: sum(weight_contribution)={total} != association={c['association']}"
        )


def test_association_within_bounds(pipeline_candidates):
    for c in pipeline_candidates:
        assert 0.0 <= c["association"] <= 1.0


def test_weights_sum_to_one():
    cfg = load_weights("config/weights.yaml")
    assert abs(sum(cfg["weights"].values()) - 1.0) < 1e-9
