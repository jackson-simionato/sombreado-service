"""Map Consórcio route snapshots onto Generation Store canonical rows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID, uuid4, uuid5

from sombreado.ingestion.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    RouteDirection,
    RouteSnapshot,
)
from sombreado.ingestion.segments import materialize_route_segments
from sombreado.store.generation import CanonicalRows

_ROUTE_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def snapshots_to_canonical_rows(snapshots: Sequence[RouteSnapshot]) -> CanonicalRows:
    """Convert fetched snapshots into one complete generation export."""
    routes: list[dict[str, object]] = []
    route_versions: list[dict[str, object]] = []
    route_directions: list[dict[str, object]] = []
    service_directions: list[dict[str, object]] = []
    route_segments: list[dict[str, object]] = []

    for snapshot in snapshots:
        route = snapshot.route
        route_id = str(uuid5(_ROUTE_NAMESPACE, route.code))
        version_id = str(uuid4())
        routes.append(
            {
                "id": route_id,
                "code": route.code,
                "name": route.name,
                "slug": route.slug,
                "category": route.category,
                "fare_region": route.fare_region,
                "last_changed": route.last_changed.isoformat() if route.last_changed else None,
                "is_current": 1,
            }
        )
        route_versions.append(
            {
                "id": version_id,
                "route_id": route_id,
                "source_hash": snapshot.source_hash,
                "map_hash": snapshot.map_hash,
                "page_url": route.page_url,
                "map_url": route.map_url,
                "is_current": 1,
            }
        )

        direction_id_by_sequence: dict[int, str] = {}
        for index, direction in enumerate(snapshot.directions, start=1):
            direction_id = str(uuid4())
            direction_id_by_sequence[index] = direction_id
            materialized = list(materialize_route_segments(direction))
            advice_segments = [
                {
                    "public_id": str(uuid4()),
                    "sequence": segment.sequence,
                    "coordinates": [[lon, lat] for lon, lat in segment.coordinates],
                    "bearing_degrees": segment.bearing_degrees,
                    "distance_meters": segment.distance_meters,
                    "cumulative_distance_meters": segment.cumulative_distance_meters,
                }
                for segment in materialized
            ]
            route_directions.append(
                {
                    "id": direction_id,
                    "route_version_id": version_id,
                    "name": direction.name,
                    "direction_kind": direction.direction_kind,
                    "sequence": index,
                    "geometry": _linestring_wkt(direction),
                    "advice_segments": advice_segments,
                }
            )
            for advice_item, segment in zip(advice_segments, materialized, strict=True):
                route_segments.append(
                    {
                        "id": advice_item["public_id"],
                        "route_version_id": version_id,
                        "route_direction_id": direction_id,
                        "sequence": segment.sequence,
                        "source_segment_sequence": segment.source_segment_sequence,
                        "source_fraction_start": segment.source_fraction_start,
                        "source_fraction_end": segment.source_fraction_end,
                        "geometry": _segment_linestring_wkt(segment.coordinates),
                        "bearing_degrees": segment.bearing_degrees,
                        "distance_meters": segment.distance_meters,
                        "cumulative_distance_meters": segment.cumulative_distance_meters,
                    }
                )

        matches = {match.service_direction_sequence: match for match in snapshot.direction_matches}
        for service in sorted(route.service_directions, key=lambda item: item.sequence):
            match = matches.get(service.sequence)
            linked_direction_id = None
            if match is not None and match.route_direction_sequence is not None:
                linked_direction_id = direction_id_by_sequence.get(match.route_direction_sequence)
            notes = dict(match.notes) if match is not None else {}
            service_directions.append(
                {
                    "id": str(uuid4()),
                    "route_version_id": version_id,
                    "route_direction_id": linked_direction_id,
                    "sequence": service.sequence,
                    "departure_label": service.departure_label,
                    "normalized_name": service.normalized_name,
                    "direction_kind": service.direction_kind,
                    "confidence": (
                        match.confidence.value if match is not None else DirectionMatchConfidence.NONE.value
                    ),
                    "method": match.method.value if match is not None else DirectionMatchMethod.UNMATCHED.value,
                    "notes": json.dumps(notes, sort_keys=True, ensure_ascii=False),
                }
            )

    return {
        "routes": routes,
        "route_versions": route_versions,
        "route_directions": route_directions,
        "service_directions": service_directions,
        "route_segments": route_segments,
    }


def hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _linestring_wkt(direction: RouteDirection) -> str:
    return "SRID=4326;LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in direction.coordinates) + ")"


def _segment_linestring_wkt(coordinates: list[tuple[float, float]]) -> str:
    return "SRID=4326;LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in coordinates) + ")"
