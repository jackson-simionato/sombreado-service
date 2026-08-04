"""Small deterministic canonical rows for store tests and fixture demos."""

from __future__ import annotations


def sample_generation_rows(*, generation_suffix: str) -> dict[str, list[dict[str, object]]]:
    """Return one self-contained generation with two short Floripa-ish segments."""
    route_id = f"route-{generation_suffix}"
    version_id = f"version-{generation_suffix}"
    direction_id = f"direction-{generation_suffix}"
    service_id = f"service-{generation_suffix}"
    segment_a_id = f"segment-{generation_suffix}-a"
    segment_b_id = f"segment-{generation_suffix}-b"
    code = f"1{generation_suffix.upper()}"

    # Short chords near the revised-app geodesic PostGIS cases.
    geometry_a = "SRID=4326;LINESTRING(-48.53424287871695 -27.58967698020161, -48.53429001602508 -27.58967384329425)"
    geometry_b = "SRID=4326;LINESTRING(-48.53423370052804 -27.58967875783012, -48.53428961785253 -27.58966823891881)"

    return {
        "routes": [
            {
                "id": route_id,
                "code": code,
                "name": f"Route {code}",
                "slug": f"route-{code.lower()}",
                "category": "conventional",
                "fare_region": None,
                "last_changed": None,
                "is_current": 1,
            }
        ],
        "route_versions": [
            {
                "id": version_id,
                "route_id": route_id,
                "source_hash": f"hash-{generation_suffix}",
                "map_hash": None,
                "page_url": "https://example.test/horarios",
                "map_url": None,
                "is_current": 1,
            }
        ],
        "route_directions": [
            {
                "id": direction_id,
                "route_version_id": version_id,
                "name": "Centro",
                "direction_kind": "ida",
                "sequence": 1,
                "geometry": geometry_a,
            }
        ],
        "service_directions": [
            {
                "id": service_id,
                "route_version_id": version_id,
                "route_direction_id": direction_id,
                "sequence": 1,
                "departure_label": "Centro",
                "normalized_name": "centro",
                "direction_kind": "ida",
                "confidence": "high",
                "method": "fixture",
                "notes": "",
            }
        ],
        "route_segments": [
            {
                "id": segment_a_id,
                "route_version_id": version_id,
                "route_direction_id": direction_id,
                "sequence": 1,
                "source_segment_sequence": 1,
                "source_fraction_start": 0.0,
                "source_fraction_end": 0.5,
                "geometry": geometry_a,
                "bearing_degrees": 270.0,
                "distance_meters": 5.0,
                "cumulative_distance_meters": 5.0,
            },
            {
                "id": segment_b_id,
                "route_version_id": version_id,
                "route_direction_id": direction_id,
                "sequence": 2,
                "source_segment_sequence": 2,
                "source_fraction_start": 0.5,
                "source_fraction_end": 1.0,
                "geometry": geometry_b,
                "bearing_degrees": 270.0,
                "distance_meters": 5.0,
                "cumulative_distance_meters": 10.0,
            },
        ],
    }
