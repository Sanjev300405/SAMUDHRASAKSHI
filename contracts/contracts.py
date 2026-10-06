"""The spine — ARCHITECTURE.md §4. Freeze hour 2; everything else is replaceable.

This is the single source of truth for the data shapes shared between backend
and frontend. `generate_ts.py` introspects these models to emit
`contracts.ts` (mirrored into `frontend/src/lib/contracts.generated.ts`) —
never hand-edit the generated files, edit this one and regenerate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Src = Literal["real", "provided", "synthetic"]
AssociationLevel = Literal["high", "medium", "low"]
EvidenceStrength = Literal["strong", "moderate", "weak"]
Uncertainty = Literal["low", "medium", "high"]
DataQuality = Literal["high", "medium", "low"]
Classification = Literal["oil", "look_alike", "uncertain"]
AgeClass = Literal["lt_6h", "6_24h", "gt_24h", "unknown"]
ForcingQuality = Literal["high", "medium", "low"]
EvidenceKind = Literal["spatial", "temporal", "trajectory", "drift", "behaviour", "quality"]

BBox = tuple[float, float, float, float]


class Provenance(BaseModel):
    """Data-source honesty, carried everywhere it applies (§0.1, §8, §7.9)."""

    sar: Src
    forcing: Src
    ais: Src


class GeoJSONPolygon(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float]]]


class SlickObservation(BaseModel):
    spill_id: str
    image_id: str
    observed_at: datetime  # UTC, satellite acquisition time
    geometry: GeoJSONPolygon  # GeoJSON Polygon, EPSG:4326
    area_km2: float
    perimeter_km: float
    length_km: float
    width_km: float
    centroid: tuple[float, float]  # (lon, lat)
    orientation_deg: float = Field(ge=0, le=180)  # major axis
    circularity: float  # 4*pi*A / P^2
    classification: Classification
    confidence: float = Field(ge=0, le=1)
    age_class: AgeClass
    provenance: Provenance  # ALWAYS carried — auditability


class OriginEstimate(BaseModel):
    spill_id: str
    probability_raster_path: str  # normalised 0-1 grid, see m4_hindcast docstring for format
    high_prob_geometry: GeoJSONPolygon  # alpha-shape of the top-density particle mass
    medium_prob_geometry: GeoJSONPolygon
    window_start: datetime
    window_end: datetime
    ensemble_size: int
    spread_km: float  # 1-sigma of particle cloud
    forcing_quality: ForcingQuality


class AISFix(BaseModel):
    ts: datetime
    lon: float
    lat: float
    sog: float  # knots
    cog: float  # degrees
    heading: float  # degrees


class AISQuality(BaseModel):
    gap_fraction: float = Field(ge=0, le=1)
    mean_interval_s: float
    jump_count: int
    implausible_speed_count: int
    score: float = Field(ge=0, le=1)  # Q


class AISTrack(BaseModel):
    track_id: str
    mmsi: str | None  # None => unidentified (SAR-only)
    vessel_type: str | None
    fixes: list[AISFix]
    quality: AISQuality
    source: Src  # SHOWN IN UI. Always.


class BestRelease(BaseModel):
    """The winning M6 hypothesis for one candidate.

    `simulated_geometry` is not spelled out in ARCHITECTURE.md §4's code
    block (only "winning (time, lon, lat, hit_rate, iou)" is named inline) —
    it is added here because the frontend swipe comparator needs a real
    polygon to draw, and M6 already computes one (the alpha-shape of the
    winning hypothesis's final particle positions). Documented, not hidden.
    """

    time: datetime
    lon: float
    lat: float
    hit_rate: float = Field(ge=0, le=1)
    iou: float = Field(ge=0, le=1)
    simulated_geometry: GeoJSONPolygon


class Evidence(BaseModel):
    kind: EvidenceKind
    label: str  # human sentence for the evidence card
    value: float
    weight_contribution: float  # how much it moved A — drives the UI bar chart
    supporting: bool  # True = supports, False = caution


class CandidateScore(BaseModel):
    candidate_id: str
    track_id: str
    spatial: float = Field(ge=0, le=1)  # S
    temporal: float = Field(ge=0, le=1)  # T
    trajectory: float = Field(ge=0, le=1)  # J
    drift_compat: float = Field(ge=0, le=1)  # D <- from M6
    behaviour: float = Field(ge=0, le=1)  # B
    ais_quality: float = Field(ge=0, le=1)  # Q (modulator, not a term)
    association: float = Field(ge=0, le=1)  # A = Q * (0.20S+0.15T+0.15J+0.35D+0.15B)
    association_level: AssociationLevel
    evidence_strength: EvidenceStrength
    uncertainty: Uncertainty
    data_quality: DataQuality
    best_release: BestRelease | None  # None when M6 found no compatible release
    evidence: list[Evidence]
    cautions: list[str]


class Weights(BaseModel):
    spatial: float
    temporal: float
    trajectory: float
    drift: float
    behaviour: float


class DriftCfg(BaseModel):
    ensemble_size: int
    particles_per_release: int
    windage_range: tuple[float, float]
    footprint_method: str
    drift_compat_norm: str


class ConfigSnapshot(BaseModel):
    weights: Weights
    drift: DriftCfg


class Assets(BaseModel):
    sar_png: str
    opm_png: str
    opm_bounds: BBox


class CaseBundle(BaseModel):
    """One object containing everything the frontend needs (§8.2). The UI
    makes ONE request; `cases/<id>/bundle.json` conforms to this exactly."""

    case_id: str
    provenance: Provenance
    observation: SlickObservation
    origin: OriginEstimate
    tracks: list[AISTrack]
    candidates: list[CandidateScore]  # pre-sorted by association, descending
    assets: Assets
    config_snapshot: ConfigSnapshot
    generated_at: datetime
