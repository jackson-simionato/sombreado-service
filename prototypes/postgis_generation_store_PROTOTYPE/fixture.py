"""Deterministic fixture generations for the PostGIS Generation Store PROTOTYPE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Point used by nearby scenarios — midpoint of generation-a segment A.
NEARBY_PROBE = (-27.58967541174793, -48.53426644737102)


@dataclass(frozen=True)
class FixtureSegment:
    id: str
    route_id: str
    route_code: str
    route_name: str
    # WKT LINESTRING in lon/lat order (PostGIS).
    linestring_wkt: str


@dataclass(frozen=True)
class FixtureGeneration:
    generation_id: str
    routes: tuple[dict[str, Any], ...]
    segments: tuple[FixtureSegment, ...]


def generation_a() -> FixtureGeneration:
    """Near the probe point (~0–5 m)."""
    return FixtureGeneration(
        generation_id="gen-a",
        routes=(
            {
                "id": "route-a",
                "code": "1A",
                "name": "Route 1A",
            },
            {
                "id": "route-far",
                "code": "99Z",
                "name": "Far Away",
            },
        ),
        segments=(
            FixtureSegment(
                id="seg-a-1",
                route_id="route-a",
                route_code="1A",
                route_name="Route 1A",
                linestring_wkt=(
                    "LINESTRING(-48.53424287871695 -27.58967698020161, -48.53429001602508 -27.58967384329425)"
                ),
            ),
            FixtureSegment(
                id="seg-far-1",
                route_id="route-far",
                route_code="99Z",
                route_name="Far Away",
                # ~2.5 km east of the probe — outside 1200 m / 2000 m radii.
                linestring_wkt="LINESTRING(-48.5100 -27.5897, -48.5095 -27.5897)",
            ),
        ),
    )


def generation_b() -> FixtureGeneration:
    """Replaces 1A with 1B at the same corridor; drops the far route."""
    return FixtureGeneration(
        generation_id="gen-b",
        routes=(
            {
                "id": "route-b",
                "code": "1B",
                "name": "Route 1B",
            },
        ),
        segments=(
            FixtureSegment(
                id="seg-b-1",
                route_id="route-b",
                route_code="1B",
                route_name="Route 1B",
                linestring_wkt=(
                    "LINESTRING(-48.53423370052804 -27.58967875783012, -48.53428961785253 -27.58966823891881)"
                ),
            ),
        ),
    )


def generation_c() -> FixtureGeneration:
    """Third publish used to prove former-previous retention drop."""
    return FixtureGeneration(
        generation_id="gen-c",
        routes=(
            {
                "id": "route-c",
                "code": "1C",
                "name": "Route 1C",
            },
        ),
        segments=(
            FixtureSegment(
                id="seg-c-1",
                route_id="route-c",
                route_code="1C",
                route_name="Route 1C",
                linestring_wkt=(
                    "LINESTRING(-48.53424287871695 -27.58967698020161, -48.53429001602508 -27.58967384329425)"
                ),
            ),
        ),
    )


def empty_generation(generation_id: str) -> FixtureGeneration:
    """Invalid export used to exercise validate-discard."""
    return FixtureGeneration(generation_id=generation_id, routes=(), segments=())
