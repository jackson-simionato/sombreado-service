"""Shared result types for the PostGIS Generation Store PROTOTYPE."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Verdict(StrEnum):
    pending = "pending"
    postgis_generation_store_credible = "postgis-generation-store-credible"
    needs_more_spike = "needs-more-spike"


@dataclass(frozen=True)
class NearbyHit:
    route_code: str
    route_name: str
    distance_meters: float


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    facts: tuple[tuple[str, str], ...]
    failures: tuple[str, ...] = ()


@dataclass
class LabState:
    database: str | None = None
    evidence_path: Path | None = None
    current_generation: str | None = None
    previous_generation: str | None = None
    lease_holder: str | None = None
    last_nearby: tuple[NearbyHit, ...] = ()
    results: dict[str, ScenarioResult] = field(default_factory=dict)
    verdict: Verdict = Verdict.pending
    spatial_model: str = "geography(LINESTRING,4326) + ST_DWithin"
