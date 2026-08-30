"""Passenger-facing direction matching and names from Consórcio scrape data."""

from sombreado.ingestion.directions import (
    infer_service_direction_matches,
    passenger_facing_direction_names,
)
from sombreado.ingestion.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    RouteDirection,
    ServiceDirection,
    ServiceDirectionMatch,
)


def _direction(name: str, kind: str | None) -> RouteDirection:
    return RouteDirection(name=name, coordinates=[(-48.5, -27.6), (-48.49, -27.6)], direction_kind=kind)


def test_two_terminal_service_labels_match_at_medium_confidence():
    matches = infer_service_direction_matches(
        [
            ServiceDirection(sequence=1, departure_label="TICEN"),
            ServiceDirection(sequence=2, departure_label="TITRI"),
        ],
        [_direction("110 - Ida", "ida"), _direction("110-Volta", "volta")],
    )

    assert [match.confidence for match in matches] == [
        DirectionMatchConfidence.MEDIUM,
        DirectionMatchConfidence.MEDIUM,
    ]
    assert [match.route_direction_sequence for match in matches] == [1, 2]


def test_complementary_terminal_labels_become_origin_to_destination_names():
    directions = [_direction("110 - Ida", "ida"), _direction("110-Volta", "volta")]
    services = [
        ServiceDirection(sequence=1, departure_label="TICEN"),
        ServiceDirection(sequence=2, departure_label="TITRI"),
    ]
    matches = infer_service_direction_matches(services, directions)

    names = passenger_facing_direction_names(
        route_code="110",
        route_directions=directions,
        service_directions=services,
        matches=matches,
    )

    assert names == ["TICEN → TITRI", "TITRI → TICEN"]


def test_missing_terminals_fall_back_to_code_and_direction_kind():
    directions = [_direction("Direção 1", "ida"), _direction("Direção 2", "volta")]

    names = passenger_facing_direction_names(
        route_code="330",
        route_directions=directions,
        service_directions=[],
        matches=[],
    )

    assert names == ["330 - Ida", "330 - Volta"]


def test_single_public_departure_label_is_used_as_direction_name():
    directions = [_direction("110 - Ida", "ida")]
    services = [ServiceDirection(sequence=1, departure_label="TICEN")]
    matches = [
        ServiceDirectionMatch(
            service_direction_sequence=1,
            route_direction_sequence=1,
            confidence=DirectionMatchConfidence.MEDIUM,
            method=DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
        )
    ]

    names = passenger_facing_direction_names(
        route_code="110",
        route_directions=directions,
        service_directions=services,
        matches=matches,
    )

    assert names == ["TICEN"]
