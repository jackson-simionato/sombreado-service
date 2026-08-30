"""Convert Consórcio route snapshots into Generation Store canonical rows."""

from sombreado.ingestion.canonical import snapshots_to_canonical_rows
from sombreado.ingestion.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    ParsedRoutePage,
    RouteDirection,
    RouteSnapshot,
    ServiceDirection,
    ServiceDirectionMatch,
)


def test_snapshots_to_canonical_rows_materializes_segments_and_membership():
    snapshot = RouteSnapshot(
        route=ParsedRoutePage(
            code="110",
            name="TICEN / TITRI",
            slug="ticen-titri",
            page_url="https://example.test/horarios/ticen-titri,110",
            map_url="https://example.test/map",
            category="conventional",
            fare_region=None,
            last_changed=None,
            service_directions=[
                ServiceDirection(sequence=1, departure_label="Centro", normalized_name="centro", direction_kind="ida")
            ],
        ),
        directions=[
            RouteDirection(
                name="Centro",
                coordinates=[(-48.53424, -27.58967), (-48.53429, -27.58967)],
                direction_kind="ida",
            )
        ],
        direction_matches=[
            ServiceDirectionMatch(
                service_direction_sequence=1,
                route_direction_sequence=1,
                confidence=DirectionMatchConfidence.HIGH,
                method=DirectionMatchMethod.LABEL_ENDPOINT,
            )
        ],
        source_hash="abc",
        map_hash="def",
    )

    rows = snapshots_to_canonical_rows([snapshot])

    assert len(rows["routes"]) == 1
    assert rows["routes"][0]["code"] == "110"
    assert len(rows["route_versions"]) == 1
    assert len(rows["route_directions"]) == 1
    assert rows["route_directions"][0]["geometry"].startswith("SRID=4326;LINESTRING(")
    assert len(rows["route_segments"]) >= 1
    assert len(rows["service_directions"]) == 1
    assert rows["service_directions"][0]["route_direction_id"] == rows["route_directions"][0]["id"]


def test_snapshots_store_passenger_facing_terminal_pair_names():
    coordinates = [(-48.53424, -27.58967), (-48.53429, -27.58967)]
    snapshot = RouteSnapshot(
        route=ParsedRoutePage(
            code="110",
            name="TICEN / TITRI",
            slug="ticen-titri",
            page_url="https://example.test/horarios/ticen-titri,110",
            map_url="https://example.test/map",
            category="executivo",
            fare_region=None,
            last_changed=None,
            service_directions=[
                ServiceDirection(sequence=1, departure_label="TICEN"),
                ServiceDirection(sequence=2, departure_label="TITRI"),
            ],
        ),
        directions=[
            RouteDirection(name="110 - Ida", coordinates=coordinates, direction_kind="ida"),
            RouteDirection(name="110-Volta", coordinates=coordinates, direction_kind="volta"),
        ],
        direction_matches=[
            ServiceDirectionMatch(
                service_direction_sequence=1,
                route_direction_sequence=1,
                confidence=DirectionMatchConfidence.MEDIUM,
                method=DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
            ),
            ServiceDirectionMatch(
                service_direction_sequence=2,
                route_direction_sequence=2,
                confidence=DirectionMatchConfidence.MEDIUM,
                method=DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
            ),
        ],
        source_hash="abc",
        map_hash="def",
    )

    rows = snapshots_to_canonical_rows([snapshot])

    assert [row["name"] for row in rows["route_directions"]] == ["TICEN → TITRI", "TITRI → TICEN"]
    assert [row["direction_kind"] for row in rows["route_directions"]] == ["ida", "volta"]
