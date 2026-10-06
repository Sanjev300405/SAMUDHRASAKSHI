# SAMUDRA SAKSHI — Architecture

**Smart India Hackathon 2026 · Problem Statement 26143**
Evidence-based satellite-to-vessel platform for oil-spill detection, origin hindcasting and explainable polluter attribution.

> **Status:** Build specification, v1.0
> **Scope:** 40-hour hackathon prototype, architected so nothing has to be thrown away afterwards.

---

## 0. How to read this document

| Section | For |
|---|---|
| 1–3 | Understanding the system and why it's shaped this way |
| 4–6 | Backend engineers |
| **7** | **Frontend / design — the largest section, deliberately** |
| 8–9 | Contracts between the two |
| 10–12 | Validation, build plan, risks |

**Source note.** Sections 1–6 and 10–12 are derived from the Samudra Sakshi Solution Document (SIH PS 26143). Section 7 and all architectural decisions marked `ADR-*` are new engineering specification, not present in that document. Anything I could not verify is flagged inline with ⚠️.

---

## 0.1 Prototype scope — READ THIS BEFORE BUILDING

> **This section governs what is being built now.** Everything below it describes the
> target system. This section says which parts are in scope for the prototype, what is
> synthetic, and what "done" means. Where this section and a later one disagree about
> scope, this one wins.

### The demo runs entirely on synthetic data

Every input — SAR scene, forcing fields, AIS — is produced by `synth/`. No network call
at demo time (ADR-004). All three data-source chips read `SYNTHETIC` with the 45° hatch
fill (§7.9). That is a **stated** limitation, not a hidden one.

This is not a compromise. ADR-003 already makes the synthetic twin core infrastructure,
because it is the only source of **ground truth** — without it there is no way to measure
top-1 / top-3 attribution hit-rate while developing.

### Synthetic data is real code. Mocked functions are not.

Two different things get called "mock". Only one is permitted here.

| Allowed | Not allowed |
|---|---|
| `synth/make_slick.py` runs real forward OpenDrift to produce a ground-truth slick | `def detect(): return {"area_km2": 4.2}` |
| `synth/make_ais.py` generates tracks with real gap / jump / loiter behaviour | A function that ignores its inputs and returns a constant |
| Uniform current + wind behind the `forcing.py` adapter, **labelled in the UI** | A module that claims to run OpenDrift but does not |

**The rule: the data may be invented; the computation may not.** M4 must actually run
OpenDrift. M6 must actually seed particles and measure hit-rate and IoU. A module that
cannot do its real work declares its stated fallback (§5) and the UI says so — it does
not pretend.

### The one permitted exception: ADR-002 fixtures

During the walking skeleton (hours 2–6) modules return hardcoded correct-shaped values so
the pipeline runs end to end before any module is real. Rules for these:

- Function name begins `fixture_`
- Carries the comment `# FIXTURE: ADR-002 — replace when <module> is real`
- Lives only in `backend/core/`, never in `synth/` or `contracts/`
- **Deleted, not commented out**, when the module becomes real
- No fixture survives into the cached demo case

`.claude/pipeline.json` enforces a banned list (`mock`, `stub`, `placeholder`, `dummy`,
`TODO`) on every file write. `fixture` is deliberately not on that list, so this convention
passes the gate without weakening it. **Do not add words to the exemptions to get code
through.**

### Per-module prototype scope

| Module | Prototype | Notes |
|---|---|---|
| M1 preprocess | minimal | Synthetic scenes need no calibration or speckle filtering. Land mask still applied. |
| M2 detect | **classical threshold** | §5 M1 option 3 — adaptive dark-spot + morphological cleanup. No trained model; the 🔴 domain-gap risk is deferred, not solved. |
| M3 characterise | **real** | `shapely` geometry. Cheap and fully real. |
| M4 hindcast | **real** | Real backward OpenDrift. Forcing from the uniform stub unless CMEMS/ERA5 are available; `forcing_quality` reports `low` when stubbed. |
| M5 AIS recon | **real** | Runs against synthetic AIS. Quality scoring `Q` is real. |
| M6 counterfactual ★ | **real, no compromise** | The differentiator. Real seeding, real hit-rate, real IoU. Never fixtured past hour 14. |
| M7 behaviour | **real rules** | Rule features on synthetic tracks. Isolation Forest deferred. |
| M8 fusion | **real** | Weights and normalisers from `config/weights.yaml`. |
| M9 console | **real** | §7 in full. This is what judges actually see. |

### Definition of done for the prototype

1. `python -m backend.cli run --case <id> --ais-source synthetic` completes and writes
   `cases/<id>/bundle.json` conforming exactly to `CaseBundle`
2. The frontend loads that bundle from `/public/cases/` and renders everything in §7.9
3. The swipe comparator shows simulated vs observed with **real** `hit_rate` and `iou`
4. `synth/run_experiments.py --n 20` emits the metrics table **including the ablation row**
5. Every data-source chip reads `SYNTHETIC`
6. No `fixture_*` function remains in any module marked **real** above
7. The §7.9 lexicon test passes — no banned word in any rendered string

### Deferred — and stated out loud, never hidden

Trained segmentation model · real SAR ingest · real AIS feeds · CMEMS / ERA5 forcing ·
Isolation Forest · mobile layout · evidence graph (the table is sufficient).

---

## 1. System overview

The system is one closed loop. A satellite sees an effect; the system works backwards through ocean physics to the cause, then tests each suspect physically.

```
  SAR / EO scene
        │
        ▼
  ┌───────────────────────────────────────┐
  │ M1–M3  DETECT · REJECT · CHARACTERISE │  slick polygon, geometry, age class
  └───────────────────────────────────────┘
        │
        ▼
  ┌───────────────────────────────────────┐
  │ M4  BACKWARD HINDCAST ENSEMBLE        │  Origin Probability Map + release window
  └───────────────────────────────────────┘
        │
        ▼
  ┌───────────────────────────────────────┐
  │ M5  AIS RECONSTRUCTION                │  reachable candidate tracks + quality score Q
  └───────────────────────────────────────┘
        │
        ▼
  ┌───────────────────────────────────────┐
  │ M6  COUNTERFACTUAL DRIFT TEST  ★      │  "would THIS vessel's release make THIS slick?"
  │ M7  BEHAVIOUR + DARK-VESSEL EVIDENCE  │
  └───────────────────────────────────────┘
        │
        ▼
  ┌───────────────────────────────────────┐
  │ M8  EXPLAINABLE EVIDENCE FUSION       │  A = Q × (0.20S + 0.15T + 0.15J + 0.35D + 0.15B)
  └───────────────────────────────────────┘
        │
        ▼
  ┌───────────────────────────────────────┐
  │ M9  INVESTIGATOR CONSOLE + REPORT     │
  └───────────────────────────────────────┘
```

★ **M6 is the differentiator.** Every other module exists to make M6 possible. Existing systems answer *"which vessel was nearest?"* — M6 answers *"which vessel's own track, run through real ocean physics, would have produced this exact slick?"*

**Non-negotiable product rule:** the system outputs *association*, never *guilt*. This constrains the UI (§7.4, §7.9) as much as the backend.

---

## 2. Architectural decisions

### ADR-001 — React console, not Streamlit

**Context.** The source document proposes Streamlit for the prototype UI. The submission is judged substantially on the interface, and requires: floating glass panels over a full-bleed map, 4K-crisp rendering, custom typography, a timeline scrubber, and an interactive evidence graph.

**Decision.** Build the frontend as **Vite + React + TypeScript + MapLibre GL + deck.gl**, served statically. Backend is FastAPI returning JSON + pre-rendered raster assets.

**Rationale.** Streamlit cannot do full-bleed map layouts, `backdrop-filter` glass, custom font loading at scale, device-pixel-ratio control, or 200ms transition choreography. Every one of those is required by §7. Fighting Streamlit for a "glossy" look costs more hours than building React properly.

**Cost.** ~6 extra hours vs Streamlit. **Mitigation:** the frontend reads a static `case.json` bundle (§8.3), so it is fully buildable and demo-able *before the backend exists*. Frontend and backend proceed in parallel from hour 2 and never block each other.

**Rejected alternative.** Next.js — SSR/routing/server actions buy nothing here and cost build complexity. This is a single-view console app.

### ADR-002 — Contracts first, walking skeleton at hour 6

**Decision.** Freeze `contracts.py` (Pydantic) + `contracts.ts` (mirrored TypeScript) in hour 2. Then build the entire pipeline end to end with every module returning **hardcoded correct-shaped fixtures**. Replace fixtures with real implementations one at a time.

**Rationale.** The source document integrates at hour 16 of 40. Integration is where this class of project dies. A running demo at hour 6 that degrades gracefully beats a perfect module that never integrates.

### ADR-003 — Synthetic twin is core infrastructure, not a fallback

**Decision.** Build the synthetic slick + synthetic AIS generator in hours 4–8, not hour 26.

**Rationale.** It is the only source of **ground truth**. With it you can measure top-1 / top-3 attribution hit-rate *while developing*. Without it you are building blind until the final day. It also removes the AIS-access risk entirely.

### ADR-004 — Demo runs from a cached case, always

**Decision.** `cases/<case_id>/` contains every artefact needed for the demo as static files. The live pipeline writes into this shape; the demo reads from it. The demo never issues a network call.

**Rationale.** No hackathon demo should depend on Copernicus uptime or venue wifi.

### ADR-005 — Single-run particle batching for M6

**Decision.** Do not issue one OpenDrift run per (vessel, release-time) pair. Seed **all** hypotheses into one simulation with per-element seed times and origin tags; partition results afterwards.

**Rationale.** OpenDrift's cost is dominated by reader initialisation, not integration. ~120 separate runs becomes 1–4. ⚠️ Verify per-element seed-time support against your pinned OpenDrift version before committing — if unsupported, batch per-vessel instead (10 runs, still a 12× win).

---

## 3. Repository layout

```
samudra-sakshi/
├── ARCHITECTURE.md
├── contracts/
│   ├── contracts.py              # Pydantic — THE SPINE. Freeze hour 2.
│   └── contracts.ts              # mirrored TS types, generated
├── backend/
│   ├── adapters/                 # provider-agnostic ingress
│   │   ├── sar.py                #   Sentinel-1 GRD / Bhoonidhi / cached scene
│   │   ├── forcing.py            #   ERA5 / CMEMS / HYCOM / uniform-field stub
│   │   └── ais.py                #   real / provided / synthetic
│   ├── core/
│   │   ├── m1_preprocess.py
│   │   ├── m2_detect.py
│   │   ├── m3_characterise.py
│   │   ├── m4_hindcast.py
│   │   ├── m5_ais_recon.py
│   │   ├── m6_counterfactual.py  # ★
│   │   ├── m7_behaviour.py
│   │   └── m8_fusion.py
│   ├── api/                      # FastAPI routers
│   ├── report/                   # WeasyPrint PDF + GeoJSON export
│   └── cli.py                    # typer — every stage runnable standalone
├── synth/
│   ├── make_slick.py             # forward OpenDrift → ground-truth slick
│   ├── make_ais.py               # true vessel + distractors + gaps + loiterers
│   └── run_experiments.py        # N randomised twins → metrics table
├── frontend/
│   ├── src/
│   │   ├── design/               # tokens, fonts, gloss primitives  ← §7
│   │   ├── map/                  # deck.gl layers
│   │   ├── panels/               # evidence dock, candidate list, timeline
│   │   └── lib/                  # case loader, formatters
│   └── public/fonts/             # self-hosted woff2 (§7.3)
├── config/
│   ├── weights.yaml              # fusion weights + normaliser params
│   ├── drift.yaml                # ensemble size, windage, diffusivity
│   └── detect.yaml               # thresholds, tile size, model path
└── cases/
    └── arabian_sea_2024/         # cached demo case (ADR-004)
```

---

## 4. Data contracts — the spine

Freeze these in hour 2. Everything else is replaceable; these are not.

```python
# contracts/contracts.py

class SlickObservation(BaseModel):
    spill_id: str
    image_id: str
    observed_at: datetime                 # UTC, satellite acquisition time
    geometry: dict                        # GeoJSON Polygon/MultiPolygon, EPSG:4326
    area_km2: float
    perimeter_km: float
    length_km: float
    width_km: float
    centroid: tuple[float, float]         # (lon, lat)
    orientation_deg: float                # 0-180, major axis
    circularity: float                    # 4*pi*A / P^2
    classification: Literal["oil", "look_alike", "uncertain"]
    confidence: float                     # 0-1
    age_class: Literal["lt_6h", "6_24h", "gt_24h", "unknown"]
    provenance: Provenance                # ALWAYS carried — auditability

class OriginEstimate(BaseModel):
    spill_id: str
    probability_raster_path: str          # COG, normalised 0-1
    high_prob_geometry: dict              # GeoJSON, >= p_high contour
    medium_prob_geometry: dict
    window_start: datetime
    window_end: datetime
    ensemble_size: int
    spread_km: float                      # 1-sigma of particle cloud
    forcing_quality: Literal["high", "medium", "low"]

class AISTrack(BaseModel):
    track_id: str
    mmsi: str | None                      # None => unidentified (SAR-only)
    vessel_type: str | None
    fixes: list[AISFix]                   # ts, lon, lat, sog, cog, heading
    quality: AISQuality                   # gap_fraction, mean_interval_s,
                                          # jump_count, implausible_speed_count, score Q
    source: Literal["real", "provided", "synthetic"]   # SHOWN IN UI. Always.

class CandidateScore(BaseModel):
    candidate_id: str
    track_id: str
    spatial: float                        # S
    temporal: float                       # T
    trajectory: float                     # J
    drift_compat: float                   # D  ← from M6
    behaviour: float                      # B
    ais_quality: float                    # Q  (modulator, not a term)
    association: float                    # A = Q * (0.20S+0.15T+0.15J+0.35D+0.15B)
    association_level: Literal["high", "medium", "low"]
    evidence_strength: Literal["strong", "moderate", "weak"]
    uncertainty: Literal["low", "medium", "high"]
    data_quality: Literal["high", "medium", "low"]
    best_release: BestRelease | None      # winning (time, lon, lat, hit_rate, iou)
    evidence: list[Evidence]
    cautions: list[str]

class Evidence(BaseModel):
    kind: Literal["spatial","temporal","trajectory","drift","behaviour","quality"]
    label: str                            # human sentence for the evidence card
    value: float
    weight_contribution: float            # how much it moved A — drives the UI bar chart
    supporting: bool                      # True = supports, False = caution
```

**Rule:** the frontend renders `CandidateScore` and nothing else. If a number is not in the contract, it does not appear on screen.

---

## 5. Backend module specification

Every module: pure function, config-driven, standalone-runnable via `cli.py`, with a declared fallback (graceful degradation, §4.3 of source doc).

### M1 — Ingestion & preprocessing

| | |
|---|---|
| **In** | GeoTIFF path or cached scene id |
| **Out** | calibrated, speckle-filtered, land-masked, tiled array + metadata |
| **Stack** | `rasterio`, `numpy`, `scipy`, coastline shapefile (GSHHG/OSM) |
| **Flags** | `--speckle {refined_lee,lee,none}` `--tile-size 256` `--overlap 32` `--land-mask PATH` |
| **Fallback** | skip calibration, use raw dB with percentile normalisation |

⚠️ **The highest-severity risk in the whole project, and it is not in the source document's risk table.** Public Sentinel-1 oil-spill segmentation datasets are typically distributed *already preprocessed* (SNAP-processed, resampled, 8-bit, 5 classes: sea / oil / look-alike / ship / land). A model trained on those will **not** transfer to a raw GRD you download yourself — the pixel statistics are unrelated.

**Resolve this in hour 1.** Three options, pick one:
1. Replicate the dataset's exact preprocessing chain on your scene (highest fidelity, highest cost, SNAP-dependent)
2. Demo on held-out images *from that dataset*, treat raw-scene ingest as roadmap (lowest risk)
3. Classical dark-spot thresholding on the real scene (source doc's own Tier-Must fallback)

I cannot verify the current dataset version, class list or licence — **read the dataset page yourself before building against it.**

### M2 — Detection & look-alike rejection

| | |
|---|---|
| **In** | tiles |
| **Out** | per-pixel class probabilities → polygons with 3-way class + confidence |
| **Stack** | `segmentation_models_pytorch` U-Net / U-Net++ (ResNet34 encoder); SegFormer as stretch |
| **Flags** | `--model PATH` `--arch {unet,unetpp,segformer}` `--p-oil 0.5` `--p-uncertain-band 0.15` `--min-area-km2 0.05` |
| **Fallback** | adaptive dark-spot threshold + morphological cleanup |

**Simplification the source document does not exploit:** if the dataset carries a `look_alike` class, three-way classification falls out of the **segmentation head directly**. The wind / GLCM / shape-irregularity rules then become a *confirmation* layer, not the mechanism. This saves several hours.

Three-way mapping: `p_oil > 0.5 + band → oil`; `p_lookalike > p_oil → look_alike`; else `uncertain`. Uncertain candidates render on the map but do **not** enter attribution by default (`--include-uncertain` to override).

### M3 — Characterisation

Geometry from `shapely`: area, perimeter, min-rotated-rectangle → length/width/orientation, `circularity = 4πA/P²`.

**Age class.** Coarse bins only (`lt_6h` / `6_24h` / `gt_24h` / `unknown`) from fragmentation and spreading cues, **hard-bounded by the time since the last clean image of the same footprint**. Never surfaced as a number. Its only job is to bound `H`, the hindcast integration horizon in M4.

### M4 — Backward hindcast ensemble

| | |
|---|---|
| **In** | slick polygon, `observed_at`, age class, forcing fields |
| **Out** | `OriginEstimate` |
| **Stack** | `OpenDrift` (`OceanDrift`), `xarray`, NetCDF readers |
| **Flags** | `--ensemble 30` `--particles 500` `--windage-range 0.02,0.04` `--current-perturb 0.15` `--timestep -600` `--horizon-h auto` |
| **Fallback** | uniform current + wind, ensemble 10 — **stated as an assumption in the UI** |

```python
# per ensemble member k
o = OceanDrift()
o.add_reader([currents, wind])
o.set_config('drift:wind_drift_factor', windage_k)      # perturbed
o.set_config('drift:horizontal_diffusivity', kappa)
o.seed_within_polygon(slick, number=N, time=observed_at)
o.run(duration=timedelta(hours=-H), time_step=-600)      # negative = backward
```

Pool particles across **all** members → 2D KDE → normalise → COG raster. Contour at `p_high` / `p_med` for the vector overlays.

**Conceptual point the source document glosses, and you must resolve before coding.** A backward run yields `origin(x, y, t)` — a 3-D field. The document presents a 2-D map plus a separate time window. Those are a *projection*. Backward drift alone cannot tell you *when*; the time window comes from **age class + last-clean-image**, which sets `H`. The map is particle density integrated over the plausible sub-window. **Write down your exact collapse rule** — M6 consumes both outputs and will silently disagree with M4 if the rule is implicit.

### M5 — AIS reconstruction

| | |
|---|---|
| **Flags** | `--buffer-km 25` `--max-speed-kn 25` `--min-fixes 5` `--source {real,provided,synthetic}` |

Pipeline: spatial filter (origin region + buffer) → temporal filter (window ± margin) → **reachability check** (could this vessel physically be at the origin region in-window at observed speeds?) → track rebuild → quality scoring.

```
Q = clamp(1 - 0.5·gap_fraction - 0.3·jump_rate - 0.2·implausible_rate, 0.2, 1.0)
```

**Missing AIS is a data-quality flag, never evidence of wrongdoing.** Enforced in code (Q only ever *lowers* confidence, never raises suspicion) and in the UI (§7.9).

### M6 — Counterfactual drift test ★

| | |
|---|---|
| **In** | candidate tracks, release window, forcing fields, observed polygon |
| **Out** | `D` per candidate + winning `BestRelease` |
| **Flags** | `--release-interval-min 12` `--particles-per-release 100` `--hit-weight 0.6` `--iou-weight 0.4` `--footprint {alpha_shape,density_contour,convex_hull}` `--alpha 0.35` |

```
for each candidate v:
  for each sampled release time t_k in [window_start, window_end]:
      p = interpolate v.track at t_k
      seed 100 particles at p, seed_time = t_k
  → ALL hypotheses into ONE OpenDrift run (ADR-005), tagged (v, t_k)
  → run forward to observed_at with the SAME forcing fields as M4
  → partition final positions by tag
      hit_rate = |particles inside observed polygon| / |particles|
      footprint = alpha_shape(final positions)     # NOT convex hull — too generous
      iou = |footprint ∩ observed| / |footprint ∪ observed|
      d_k = 0.6·hit_rate + 0.4·iou
  D_v = max_k d_k ;  best_release = argmax_k
```

**Two specification gaps the source document leaves open — decide and document:**
1. **`hit_rate` + `iou` → `D` combination.** Default above is `0.6 / 0.4`, configurable. Be ready to defend it.
2. **Particle cloud → polygon.** Convex hull is too generous and will inflate every IoU. Use alpha-shape or a density-threshold contour. This choice materially changes rankings.

**Using the same forcing fields as M4 is mandatory.** Different fields between hindcast and counterfactual makes the test meaningless.

### M7 — Behaviour & dark vessels

Rule features per track, each normalised 0–1, combined → `B`:
`unexpected_stop`, `sharp_turn` (Δheading > θ), `slowdown`, `loitering` (low net displacement over window), `ais_gap_in_window`.

SAR ship detection: CFAR ideally; a size/aspect-filtered adaptive threshold on the land-masked scene is a defensible prototype. Detections with no AIS match within tolerance become **unidentified candidates** — they enter the ranked list with `mmsi = None` and a permanently capped `Q`.

Isolation Forest only if hours remain. It adds little and costs explainability, which is the entire pitch.

### M8 — Fusion

```
A = Q × (0.20·S + 0.15·T + 0.15·J + 0.35·D + 0.15·B)
```

Weights sum to 1.00. `D` carries the most weight because it is the only factor testing physical plausibility.

**The real specification gap.** The source document defines *what each factor answers* but not **how to normalise raw quantities into 0–1**. Define these explicitly in `config/weights.yaml`:

```yaml
weights:       {spatial: 0.20, temporal: 0.15, trajectory: 0.15, drift: 0.35, behaviour: 0.15}
normalisers:
  spatial:     {method: opm_sample_at_closest_approach, divisor: map_max}
  temporal:    {method: window_coverage_fraction}
  trajectory:  {method: axis_alignment, form: "0.5*track_intersects + 0.5*(1 - |Δθ|/90)"}
  drift:       {hit_weight: 0.6, iou_weight: 0.4}
  behaviour:   {method: max_of_rules}
levels:        {high: 0.70, medium: 0.40}
sensitivity:   {sweep_pct: 20, steps: 5}
```

`J` (trajectory) is the vaguest factor in the source document. The form above is a concrete proposal, **not from the source** — replace it if you have better.

Every factor also emits an `Evidence` row with `weight_contribution` = its share of `A`. That field is what drives the evidence-card bar chart in §7.9. **Scores and explanations are produced in the same pass** — never reconstructed afterwards.

---

## 6. Compute & performance budget

| Stage | Cost | Notes |
|---|---|---|
| M1 preprocess | 20–60 s | one-time per scene, cached |
| M2 inference | 5–15 s | GPU; ~60 s CPU |
| M4 hindcast | 30–90 s | 30 members × 500 particles |
| M6 counterfactual | **20–60 s** | with ADR-005 batching; **10–20 min without it** |
| M7 + M8 | < 2 s | |
| **Cold total** | **~2–4 min** | |
| **Cached demo** | **< 1 s** | ADR-004 — this is what runs on stage |

---

## 7. Frontend architecture — the console

> This section is the differentiator in the room. Judges see the UI for 6 minutes and the code for 0.

### 7.1 Design position

**This is an instrument, not a website.** The reference class is a maritime intelligence console — mission control, ECDIS, defence GIS. It is **not** a SaaS dashboard and **not** a landing page.

One sentence to design against:

> *A dark, full-bleed ocean map with weightless glass instruments floating over it, dense with honest numbers, using exactly one accent colour — earned, never decorative.*

#### The anti-AI-generated checklist

These are the specific tells that make an interface read as machine-produced. Every one is banned:

| ✗ Banned | ✓ Instead |
|---|---|
| Purple→indigo→blue gradients | One accent hue (amber), used on < 5% of pixels |
| Emoji anywhere in the UI | Vector glyphs, 1.5px stroke, domain-specific |
| Identical corner radius on everything | Radius by elevation: `4px` controls · `10px` panels · `0px` map chrome |
| Centered hero with big gradient headline | No hero. The map *is* the page, from pixel 0. |
| Uniform 3-across card grid | Asymmetric console: rail / map / dock |
| Inter at 400 + 600 only | Three families, six weights, real optical intent (§7.3) |
| Traffic-light red/amber/green pills | Single-hue intensity ramp + a written word |
| Drop shadows all the same | Three-layer elevation system (§7.5) |
| `border-radius: 9999px` on every badge | Squared-off technical labels, `2px` radius |
| Decorative motion, bouncy easing | 180–240ms, one easing curve, state changes only |
| Generic stock iconography | Vessel glyphs that differ by vessel type; heading arrows that point |

**The single highest-leverage decision:** the map bleeds edge-to-edge under translucent floating panels. It does not sit *inside* a card, *beside* a sidebar, or *under* a header bar. That one choice does more "this is a real product" work than everything else combined.

### 7.2 Layout system

```
┌────┬─────────────────────────────────────────────┬─────────────────┐
│    │                                             │                 │
│ R  │                                             │  EVIDENCE DOCK  │
│ A  │     MAP — FULL BLEED, edge to edge          │  ┌───────────┐  │
│ I  │                                             │  │ candidate │  │
│ L  │   ┌──────────────┐                          │  │  card     │  │
│    │   │ SLICK READOUT│ ← floats, glass          │  └───────────┘  │
│ 56 │   │ 4.2 km²      │                          │  ┌───────────┐  │
│ px │   └──────────────┘                          │  │ evidence  │  │
│    │                                             │  │  bars     │  │
│    │                          ┌───────────────┐  │  └───────────┘  │
│    │                          │ SCALE · N · Q │  │  ┌───────────┐  │
│    │                          └───────────────┘  │  │ evidence  │  │
│    ├─────────────────────────────────────────────┤  │  graph    │  │
│    │  ◀ TIMELINE SCRUBBER — release window ▶     │  └───────────┘  │
└────┴─────────────────────────────────────────────┴─────────────────┘
  56px            fluid, min 720px                     380px fixed
```

- **Rail (56px):** icon-only stage navigation — Detect · Origin · Traffic · Simulate · Report. Active stage marked by a 2px accent bar on the *left edge*, not a filled pill.
- **Map:** full viewport. All panels are `position: absolute` over it.
- **Dock (380px):** glass, scrollable, the only place numbers live.
- **Timeline (72px):** spans the map width, glass, scrubs the release window and replays AIS.

Responsive: below 1280px the dock becomes an overlay drawer. **Do not build a mobile layout** — this is a desk instrument and hours are finite. State that as a design decision, not an omission.

### 7.3 Typography

Three families. Each has a job. This is where "rich" is won or lost.

| Role | Family | Weights | Used for |
|---|---|---|---|
| **Editorial** | **Instrument Serif** | 400, 400i | Wordmark, report headings, the association verdict line. **Nothing else.** |
| **Interface** | **Satoshi** (Fontshare) | 400, 500, 700 | All labels, buttons, body, panel titles |
| **Data** | **IBM Plex Mono** | 400, 500, 600 | Every number, coordinate, MMSI, timestamp, score |

**Why this pairing reads as expensive:** a high-contrast display serif next to a geometric grotesque next to an institutional mono is a *deliberate editorial decision*. Inter-everywhere is the default, and defaults read as unconsidered. The serif wordmark alone — `SAMUDRA SAKSHI` in Instrument Serif italic, letterspaced, beside mono coordinates — carries most of the perceived quality.

⚠️ **Verify before building.** I have not confirmed current availability or licensing. Satoshi is distributed by Fontshare (free, ITF licence) and IBM Plex Mono / Instrument Serif via Google Fonts — **check each licence page yourself.** Fallback if Fontshare is unreachable: `Inter Tight` for the interface role. Do not substitute the mono or the serif; those two do the heavy lifting.

**Self-host all three as `woff2` in `/public/fonts`.** Never use Google Fonts `<link>` — venue wifi will fail you on stage, and FOUT on a dark UI looks broken.

```css
@font-face{font-family:'Satoshi';src:url('/fonts/Satoshi-Variable.woff2')format('woff2-variations');
  font-weight:300 900;font-display:block}
```

`font-display: block` — on a dark console, invisible text for 100ms beats a flash of Times New Roman.

#### Type scale (1.250 major third, 4K-safe)

```css
--t-display: 2.986rem/1.05   /* Instrument Serif — wordmark only */
--t-h1:      1.563rem/1.20
--t-h2:      1.250rem/1.30
--t-body:    0.875rem/1.55
--t-label:   0.750rem/1.30   /* +0.08em tracking, uppercase */
--t-micro:   0.688rem/1.25   /* +0.10em tracking */
--t-data-lg: 1.953rem/1.10   /* Plex Mono, tabular */
--t-data:    0.875rem/1.40
```

#### Non-negotiable text rules

```css
/* EVERY numeric element. Without this, columns jitter as values update
   and the whole console reads as amateur. */
.num { font-variant-numeric: tabular-nums lining-nums;
       font-feature-settings: "tnum" 1, "lnum" 1; }

html { -webkit-font-smoothing: antialiased;
       -moz-osx-font-smoothing: grayscale;
       text-rendering: optimizeLegibility; }

/* Labels never sentence-case. Technical registers use caps + tracking. */
.label { text-transform: uppercase; letter-spacing: 0.08em; font-weight: 500; }
```

### 7.4 Colour & tokens

Dark-primary. SAR imagery is greyscale; a dark surface makes it legible and makes the single accent sing.

```css
:root {
  /* Surfaces — cool near-black, never pure #000 (crushes shadows on OLED) */
  --s-void:      #05080C;   /* behind everything */
  --s-deep:      #0A0F16;   /* map background / no-data ocean */
  --s-panel:     #0D131C;   /* glass base, used at ~72% alpha */
  --s-raised:    #131A25;   /* inputs, hovered rows */
  --s-line:      #1E2836;   /* hairlines */

  /* Text */
  --fg-primary:  #E8EDF4;
  --fg-secondary:#9AA8BC;
  --fg-tertiary: #5F6D82;
  --fg-inverse:  #05080C;

  /* THE accent. Oil amber. Used on <5% of pixels. Earn every use. */
  --accent:      #F5A524;
  --accent-dim:  #B8781A;
  --accent-glow: rgb(245 165 36 / 0.16);

  /* Domain semantics — NOT traffic lights */
  --slick:       #F5A524;   /* observed slick — the accent, because it IS the subject */
  --origin-hi:   #FF6B4A;   /* origin probability ramp, perceptually uniform */
  --origin-md:   #C7527F;
  --origin-lo:   #6B4E9E;
  --track:       #4AC8E0;   /* AIS tracks — cool, recedes behind the slick */
  --track-sel:   #8FF0FF;
  --sim:         #7DD3A0;   /* simulated counterfactual slick */
  --dark-vessel: #8B93A3;   /* unidentified — deliberately colourless */
  --caution:     #E0A0A0;   /* cautions. MUTED. Never alarm-red. */
}
```

**Association levels are not traffic lights.** Red/amber/green is both a cliché and an accessibility failure, and it implies guilt — which this product explicitly refuses to do. Instead: **one hue, three intensities, plus the word**.

```
HIGH     ███████████░░░  0.84   ← accent at 100%, word in Instrument Serif
MEDIUM   ██████░░░░░░░░  0.52   ← accent at 55%
LOW      ██░░░░░░░░░░░░  0.21   ← accent at 28%
```

Contrast floor: **4.5:1** for all text ≥ 4.5:1 against its actual glass backdrop — not against `--s-void`. Test against the map showing through.

### 7.5 The material system — how "glossy" is actually built

Gloss is not one CSS property. It is four layers, composited:

1. **Backdrop blur + saturation** — the map bleeds through, colour-boosted
2. **A vertical sheen** — light falls from above
3. **A specular top edge** — a 1px inset highlight; this is what reads as *glass*, not *frosted plastic*
4. **Layered shadow** — contact + ambient, two different spreads

```css
.panel {
  position: relative;
  border-radius: 10px;
  border: 1px solid rgb(255 255 255 / 0.07);

  /* 2 — sheen over 3 — translucent base */
  background:
    linear-gradient(180deg, rgb(255 255 255 / 0.048) 0%,
                            rgb(255 255 255 / 0.012) 38%,
                            rgb(255 255 255 / 0) 62%),
    rgb(13 19 28 / 0.72);

  /* 1 — the map shows through, saturated */
  backdrop-filter: blur(24px) saturate(150%);
  -webkit-backdrop-filter: blur(24px) saturate(150%);

  box-shadow:
    inset 0 1px 0 0 rgb(255 255 255 / 0.09),   /* 3 — SPECULAR EDGE. The key line. */
    inset 0 0 0 1px rgb(255 255 255 / 0.02),
    0 1px 2px -1px rgb(0 0 0 / 0.60),          /* 4a — contact */
    0 16px 40px -12px rgb(0 0 0 / 0.70);       /* 4b — ambient */
}

/* Hairline sheen sweep across the top 1/3 — the "expensive" detail */
.panel::before {
  content:''; position:absolute; inset:0 0 auto 0; height:33%;
  border-radius:10px 10px 0 0; pointer-events:none;
  background: radial-gradient(120% 100% at 50% 0%,
              rgb(255 255 255 / 0.055) 0%, transparent 70%);
}
```

**Grain overlay — do not skip this.** Large smooth gradients on a 4K panel show visible banding. A ~2.5% opacity noise layer destroys banding and adds a tactile, photographic quality that is a strong anti-AI signal.

```css
.grain::after {
  content:''; position:fixed; inset:0; pointer-events:none; z-index:9999;
  opacity:0.025; mix-blend-mode:overlay;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
```

**Elevation ladder** — three levels, never more:

| Level | Use | Blur | Shadow |
|---|---|---|---|
| `e1` | inline chips, table rows | none | `inset 0 1px 0 rgb(255 255 255/.04)` |
| `e2` | floating panels, dock | 24px | contact + ambient (above) |
| `e3` | modals, report preview | 40px | `0 32px 80px -16px rgb(0 0 0/.85)` |

⚠️ `backdrop-filter` over a WebGL canvas is GPU-expensive. Budget **at most 5 blurred surfaces on screen**. If the demo machine drops below 50fps, reduce blur to 12px before removing panels.

### 7.6 4K / high-DPI rendering rules

"4K clarity" is not a resolution setting — it is a set of constraints that prevent softness.

```
✓ Every icon is inline SVG. Zero raster UI assets. 1.5px stroke at 24px.
✓ deck.gl:   useDevicePixels: true
✓ MapLibre:  pixelRatio: window.devicePixelRatio  (cap at 2 for perf)
✓ Raster tiles requested @2x; if unavailable, prefer vector
✓ SAR chips rendered by the backend at 2× their CSS box, downscaled by the browser
✓ SAR at >100% zoom: image-rendering: pixelated
    → show honest sensor pixels. Smoothing SAR is a scientific lie AND looks soft.
✗ NEVER transform: scale() on text — it resamples glyphs and destroys hinting
✗ NEVER 0.5px borders — use 1px + a low-alpha colour
✗ NEVER a PNG where an SVG will do
```

```css
@media (min-resolution: 2dppx) {
  :root { --hairline: rgb(255 255 255 / 0.055); }   /* hairlines read heavier at 2x */
  .panel { border-width: 0.5px; }                    /* only valid AT 2dppx */
}
```

**Canvas sizing — get this wrong and everything is blurry:**

```ts
const dpr = Math.min(window.devicePixelRatio || 1, 2);
canvas.width  = cssWidth  * dpr;     // backing store
canvas.height = cssHeight * dpr;
canvas.style.width  = `${cssWidth}px`;   // CSS size
canvas.style.height = `${cssHeight}px`;
ctx.scale(dpr, dpr);
```

### 7.7 Map rendering stack

**MapLibre GL** for basemap + camera. **deck.gl** overlaid via `MapboxOverlay` for all data layers.

| z | Layer | deck.gl type | Notes |
|---|---|---|---|
| 0 | Basemap | MapLibre | Dark, **label-suppressed** ocean style. Land at 30% opacity — it is context, not content. |
| 1 | SAR scene | `BitmapLayer` | 2× resolution, `pixelated` at high zoom |
| 2 | Origin Probability Map | `BitmapLayer` / `HeatmapLayer` | `origin-lo → md → hi` ramp, additive blend |
| 3 | Origin contours | `GeoJsonLayer` | 1.5px, dashed for medium |
| 4 | AIS tracks | `TripsLayer` | **animated with the scrubber** — the strongest single visual in the demo |
| 5 | Simulated slick (M6) | `PolygonLayer` | `--sim`, 35% fill, 2px stroke |
| 6 | **Observed slick** | `PolygonLayer` | `--slick`, 28% fill, **2.5px stroke, always on top** — the subject |
| 7 | Vessels | `IconLayer` | SVG atlas, **rotated to true heading**, glyph varies by vessel type |
| 8 | Selection | `ScatterplotLayer` | pulsing 1.5s ring on the selected candidate |

**The money shot.** Source document §10.2 step 6: simulated slick vs observed slick, side by side. Build this as a **swipe comparator** — a draggable vertical divider over the map, mono readout showing `hit-rate 71% · IoU 0.43` pinned to the divider. That single interaction makes the counterfactual idea legible in five seconds, which is the entire pitch.

### 7.8 Motion

```css
--ease:      cubic-bezier(0.22, 0.75, 0.25, 1);   /* ONE curve. Everywhere. */
--d-fast:    140ms;   /* hover, focus */
--d-base:    200ms;   /* panel enter, selection */
--d-slow:    320ms;   /* stage transitions */
--d-camera:  900ms;   /* map flyTo */
```

Rules: motion communicates **state change** only — never decoration. No bounce, no spring, no stagger longer than 40ms. Camera moves use `flyTo` with eased curve. Respect `prefers-reduced-motion: reduce` → all durations to `1ms` except the AIS scrubber, which is content.

### 7.9 Component inventory

| Component | Spec |
|---|---|
| **Wordmark** | `SAMUDRA SAKSHI` — Instrument Serif italic, `0.06em` tracking, `--fg-primary`. Beneath: `— THE OCEAN WITNESS —` in micro caps, `--fg-tertiary`. |
| **Stage rail** | 56px, icon-only, active = 2px accent bar on left edge + icon at full opacity. Inactive icons at 45%. |
| **Slick readout** | Floating `e2` panel, top-left of map. `4.2` in `--t-data-lg` mono, `km²` in micro caps beside it. Plus class chip + confidence. |
| **Candidate row** | Height 64px. Left: vessel glyph + name/MMSI (mono). Centre: association bar (§7.4). Right: `0.84` mono, `--t-data`. Hover raises to `--s-raised` + 1px accent left edge. |
| **Evidence card** | The core explainability artefact. Five horizontal bars — S/T/J/D/B — each showing `weight_contribution`. **Cautions render below in `--caution`, never mixed into the supporting bars.** Footer line, always present, Instrument Serif: *"Evidence-based association only. Not legal proof."* |
| **Evidence graph** | Force-directed, `d3-force` in SVG (not canvas — needs crisp text). Vessel node centre; evidence nodes radial; edge thickness = `weight_contribution`. Stretch item — a clean table beats a messy graph. |
| **Timeline scrubber** | Full map width, `e2` glass. Release window as an accent-tinted band. Drag scrubs AIS replay. Tick labels mono, tabular. |
| **Data-source chip** | **Mandatory, always visible.** `REAL` / `PROVIDED` / `SYNTHETIC` for each of SAR / forcing / AIS. Synthetic renders with a 45° hatch fill. This is an honesty requirement from the source document (§8, "Transparency") — and judges reward a stated limitation over a discovered overstatement. |
| **AIS-quality meter** | Q as a 5-segment bar. Gaps render as *empty* segments. Tooltip names the gap duration. Never coloured red. |
| **Uncertainty band** | Every score displays `±` spread from the ensemble. A number without uncertainty is not shown. |

#### Language enforcement, in code

```ts
// frontend/src/lib/lexicon.ts
export const BANNED = ['guilt','guilty','culprit','offender','responsible','proven','blame'];
// dev-only assertion over all rendered strings — fail loud in CI
```

The source document (Table 4) states these words are never shown. Make that a test, not a promise.

### 7.10 Accessibility

- 4.5:1 minimum contrast **against the actual glass backdrop**, with the map showing through. Test with the busiest basemap tile behind.
- Association level always carries the **word**, never colour alone.
- Full keyboard path: `Tab` through candidates, `↑/↓` list nav, `Space` selects, `Esc` closes dock.
- `prefers-reduced-motion` honoured.
- All map layers have a tabular equivalent — the map is not the only route to any datum.

---

## 8. API surface

### 8.1 Endpoints

```
POST /api/v1/cases                        → {case_id}         create from scene
GET  /api/v1/cases/{id}                   → CaseBundle        everything, one call
POST /api/v1/cases/{id}/detect            → SlickObservation
POST /api/v1/cases/{id}/hindcast          → OriginEstimate
POST /api/v1/cases/{id}/traffic           → AISTrack[]
POST /api/v1/cases/{id}/simulate          → CandidateScore[]  M6 + M7 + M8
GET  /api/v1/cases/{id}/report.pdf
GET  /api/v1/cases/{id}/export.geojson
GET  /api/v1/cases/{id}/assets/{name}     → COG / PNG / tiles
```

Each POST mirrors one dashboard button. Long-running calls return `202` + a poll token; the UI shows a determinate progress rail, never a spinner.

### 8.2 The `CaseBundle`

One object containing everything the frontend needs. The UI makes **one** request.

```ts
interface CaseBundle {
  case_id: string;
  provenance: { sar: Src; forcing: Src; ais: Src };   // Src = 'real'|'provided'|'synthetic'
  observation: SlickObservation;
  origin: OriginEstimate;
  tracks: AISTrack[];
  candidates: CandidateScore[];      // pre-sorted by association, descending
  assets: { sar_png: string; opm_png: string; opm_bounds: BBox };
  config_snapshot: { weights: Weights; drift: DriftCfg };   // reproducibility
  generated_at: string;
}
```

### 8.3 Static-first contract (this is what unblocks parallel work)

`cases/<id>/bundle.json` conforms to `CaseBundle` exactly. The frontend loads it from `/public/cases/` during development.

**Consequence: the entire frontend is buildable and demo-able before any backend endpoint exists.** Hand-write one `bundle.json` in hour 2. Frontend work never blocks on backend work again.

---

## 9. Configuration

Nothing hardcoded. Every behavioural parameter is a YAML key with a CLI override (per project convention: flags on the interface, not values buried in internals).

```bash
python -m backend.cli run \
  --case arabian_sea_2024 \
  --detect-arch unetpp --p-oil 0.55 \
  --ensemble 30 --particles 500 --windage-range 0.02,0.04 \
  --release-interval-min 12 --particles-per-release 100 \
  --hit-weight 0.6 --iou-weight 0.4 --footprint alpha_shape \
  --weights config/weights.yaml \
  --ais-source synthetic \
  --out cases/arabian_sea_2024/
```

The `--weights` file is swept by `synth/run_experiments.py --sweep 20` to produce the ±20% sensitivity view required by the source document's Table 11.

---

## 10. Validation harness

Runs headless, emits a metrics table straight into the slide deck.

```bash
python -m synth.run_experiments --n 50 --seed 42 --out results/
```

Per the source document's Table 11:

| Metric | Reported as |
|---|---|
| Segmentation IoU / F1 | per class, incl. look-alike, held-out |
| Look-alike false-alarm rate | on held-out negatives |
| Origin recovery error | km from true origin to probability-weighted centre; % of true origins inside high-prob region |
| **Top-1 / top-3 attribution hit-rate** | **the headline number** |
| **Ablation: proximity-only vs full fusion vs fusion-without-D** | **proves M6 earns its 0.35 weight** |
| Weight sensitivity | rank stability under ±20% |
| Latency | scene → ranked candidates, demo machine |

The ablation row is the most persuasive artefact in the entire submission. It converts "we built a clever thing" into "the clever thing measurably works." Budget time for it.

Report failures as measured — long release-to-observation delays, sparse AIS. A stated limitation beats a discovered one.

---

## 11. Build plan — 40 hours

### Split: what I can do vs what only you can do

**AI can do directly:** all contracts, all backend module code, the synthetic generators, the entire frontend and design system, the validation harness, the report templates, README and slides.

**Manual — only you can do these:**

| # | Task | Why it needs you |
|---|---|---|
| M1 | Register Copernicus Data Space (SAR) | account + approval |
| M2 | Register CDS for ERA5 + install `~/.cdsapirc` | API key is personal |
| M3 | Register Copernicus Marine for CMEMS | account + approval |
| M4 | Read the Sentinel-1 segmentation dataset page — confirm version, class list, licence | licence decision is yours (§5 M1 ⚠️) |
| M5 | Download `Satoshi` from Fontshare + confirm its licence | licence acceptance |
| M6 | Pick and lock the historical case | domain judgement |
| M7 | Provide a GPU (Colab/Kaggle) for fine-tuning | your account |

**Do M1–M3 in the first hour.** Registration latency, not code, is what kills the schedule.

I will walk you through each manual step one at a time — one step, then wait for your confirmation, then the next. I will not dump them on you as a block.

### Schedule

| Hours | Work | Gate |
|---|---|---|
| **0–2** | Manual steps M1–M4. Repo init. **Freeze `contracts.py` + `contracts.ts`.** Hand-write `bundle.json` fixture. | Contracts frozen |
| **2–6** | **Walking skeleton (ADR-002):** every module returns a fixture; frontend renders the real fixture bundle. | ✅ **Demo runs at hour 6** |
| **4–8** | **Synthetic twin (ADR-003):** forward-drift slick + synthetic AIS with a known true vessel. | Ground truth exists |
| **6–14** | *Parallel A:* design tokens → layout → map layers → candidate list. *Parallel B:* M4 hindcast real; M5 AIS real. | |
| **14–20** | **M6 counterfactual real** (with ADR-005 batching) + M8 fusion real. Swipe comparator built. | ★ core works |
| **20–26** | M2 detection real (per the hour-1 decision). M7 behaviour + dark vessels. Evidence card. | |
| **26–31** | Polish pass: gloss, grain, 4K audit, motion, empty/error states, keyboard path. | UI locked |
| **31–35** | Validation runs + ablation. PDF report. Sensitivity view. | Numbers in hand |
| **35–38** | **Cache the demo case (ADR-004).** Rehearse the 6-minute flow. Record backup video. | Demo-proof |
| **38–40** | README, slides, architecture diagram, buffer. | |
| | **CODE FREEZE AT HOUR 36.** Hours 36–40 are documentation and rehearsal only. | |

### Demo flow (6 minutes, rehearse it verbatim)

1. Scene loads · data-source chips visible from second one *(honesty first)*
2. **Detect** → slick segments, geometry readout counts up
3. **Trace Origin** → Origin Probability Map blooms, window band appears on the timeline
4. **Analyse Traffic** → AIS tracks animate through the window via `TripsLayer`
5. Select a candidate → evidence card slides into the dock
6. **Run Simulation** → **swipe comparator**: simulated vs observed. `hit-rate 71% · IoU 0.43` ← *the pitch*
7. Comparison against the publicly reported source for the case
8. **Generate Report** → PDF, with the "not legal proof" line visible on screen

---

## 12. Risk register

Ordered by *my* assessment of real severity, which differs from the source document's Table 12 (which weights all risks equally).

| Risk | Severity | Mitigation |
|---|---|---|
| **SAR train/infer domain gap** (§5 M1) | 🔴 Critical | Decide in hour 1 among the three options. **Not in the source document's risk table.** |
| **Forcing-data access latency** (ERA5/CMEMS) | 🔴 High | Register hour 0. Uniform-field stub behind the same adapter, labelled in the UI. |
| **M6 runtime** | 🟠 Medium | ADR-005 batching. Fall back to per-vessel batching if per-element seeding is unsupported. |
| **Undefined score normalisers** | 🟠 Medium | Fixed in `config/weights.yaml` §5 M8. Will silently break integration if left implicit. |
| **`backdrop-filter` perf over WebGL** | 🟠 Medium | ≤5 blurred surfaces; reduce blur to 12px before removing panels. Test on the actual demo machine. |
| **Frontend scope creep** (ADR-001 cost) | 🟠 Medium | Evidence *graph* is the only stretch item. A clean table beats a messy graph. Freeze at hour 31. |
| AIS access | 🟢 Low | Synthetic generator is the better choice regardless — it provides ground truth. |
| Look-alikes | 🟢 Low | Segmentation head handles it if the dataset carries the class. |
| False attribution | 🟢 Low *(technically)* | Association language enforced in code (§7.9). Reputationally this is the highest risk — treat the lexicon test as non-negotiable. |

---

## 13. Open decisions — resolve before coding

| # | Decision | Owner | By hour |
|---|---|---|---|
| 1 | Exact time-window derivation: age class + last-clean-image → `H` | backend | 4 |
| 2 | `hit_rate` / `IoU` → `D` combination weights | backend | 14 |
| 3 | Normaliser for `J` (trajectory) — vaguest factor in the source doc | backend | 14 |
| 4 | Particle cloud → polygon method (alpha-shape vs density contour) | backend | 14 |
| 5 | Historical case selection | you | 2 |
| 6 | Segmentation dataset: version, classes, licence | you | 1 |
| 7 | Confirm Satoshi / Instrument Serif / IBM Plex Mono licensing | you | 2 |

---

## Appendix A — Design tokens, single source of truth

```
Radius      control 4px · panel 10px · modal 14px · map-chrome 0px
Space       4 · 8 · 12 · 16 · 24 · 32 · 48 · 64   (4px base)
Rail        56px     Dock 380px     Timeline 72px
Blur        e2 24px · e3 40px       (perf cap: 5 surfaces)
Stroke      icons 1.5px @24 · hairline 1px · slick 2.5px · sim 2px
Grain       2.5% overlay, mix-blend overlay
Easing      cubic-bezier(0.22,0.75,0.25,1) — one curve, everywhere
Duration    140 / 200 / 320 / 900(camera) ms
Accent      #F5A524, <5% of pixels
Numerics    tabular-nums lining-nums — mandatory on every number
Contrast    4.5:1 minimum, measured against the glass backdrop
```

## Appendix B — Frontend dependencies

```
react  react-dom  typescript  vite
maplibre-gl  deck.gl  @deck.gl/layers  @deck.gl/geo-layers  @deck.gl/mapbox
d3-force  d3-scale  d3-shape
zustand              # single case-bundle store, no prop drilling
tailwindcss          # tokens in @theme; components hand-written, no UI kit
```

**No component library.** shadcn / MUI / Chakra carry recognisable default shapes — the exact "AI-generated" signature §7.1 bans. The component inventory is ~14 items. Hand-build them.

---

*Sections 1–6, 10 and 12 derive from the Samudra Sakshi Solution Document (SIH PS 26143). Sections 7–9, 11, 13 and all `ADR-*` decisions are new engineering specification. Items marked ⚠️ are unverified and require primary-source confirmation before implementation.*
