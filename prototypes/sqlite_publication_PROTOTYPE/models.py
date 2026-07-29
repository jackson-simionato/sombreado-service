"""Shared result types for the throwaway publication decision lab."""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Verdict(StrEnum):
    pending = "pending"
    core_sqlite_credible = "core-sqlite-credible"
    fallback_postgis = "fallback-postgis"


@dataclass(frozen=True)
class NearbySample:
    lat: float
    lng: float
    radius_meters: float


@dataclass(frozen=True)
class BehaviorSnapshot:
    identities: tuple[tuple[str, ...], ...]
    direction_labels: tuple[tuple[str, ...], ...]
    geometry: tuple[tuple[str, ...], ...]
    stale_version_results: tuple[tuple[str, str], ...]
    nearby: tuple[tuple[NearbySample, tuple[tuple[str, float], ...]], ...]


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    facts: tuple[tuple[str, str], ...]
    failures: tuple[str, ...] = ()


@dataclass
class LabState:
    temp_dir: Path | None = None
    active_generation: str | None = None
    staging_generation: str | None = None
    results: dict[str, ScenarioResult] = field(default_factory=dict)
    verdict: Verdict = Verdict.pending
