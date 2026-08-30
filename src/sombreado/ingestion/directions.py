from __future__ import annotations

import re
import unicodedata

from sombreado.ingestion.domain import (
    DirectionMatchConfidence,
    DirectionMatchMethod,
    RouteDirection,
    ServiceDirection,
    ServiceDirectionMatch,
)

TERMINAL_TOKENS = ("ticen", "titri", "tican", "tirio", "tilag", "tisan", "terminal")
_DIRECTION_KIND_PATTERN = re.compile(r"\b(ida|volta)\b", re.IGNORECASE)
_PUBLIC_MATCH_CONFIDENCES = {DirectionMatchConfidence.HIGH, DirectionMatchConfidence.MEDIUM}


def passenger_facing_direction_names(
    *,
    route_code: str,
    route_directions: list[RouteDirection],
    service_directions: list[ServiceDirection],
    matches: list[ServiceDirectionMatch],
) -> list[str]:
    match_by_service = {match.service_direction_sequence: match for match in matches}
    origin_by_route_sequence: dict[int, str] = {}
    for service in sorted(service_directions, key=lambda item: item.sequence):
        match = match_by_service.get(service.sequence)
        if (
            match is None
            or match.route_direction_sequence is None
            or match.confidence not in _PUBLIC_MATCH_CONFIDENCES
            or match.route_direction_sequence in origin_by_route_sequence
        ):
            continue
        origin_by_route_sequence[match.route_direction_sequence] = service.departure_label

    origins = [origin_by_route_sequence.get(index) for index in range(1, len(route_directions) + 1)]
    has_origin_destination_pair = (
        len(origins) == 2 and bool(origins[0]) and bool(origins[1]) and origins[0] != origins[1]
    )
    names: list[str] = []
    for index, direction in enumerate(route_directions):
        origin = origins[index]
        if has_origin_destination_pair:
            names.append(f"{origin} → {origins[1 - index]}")
        elif origin:
            names.append(origin)
        elif direction.direction_kind:
            names.append(f"{route_code} - {direction.direction_kind.title()}")
        else:
            names.append(direction.name)
    return names


def classify_route_direction_pair(route_directions: list[RouteDirection]) -> None:
    for direction in route_directions:
        direction.direction_kind = None

    if len(route_directions) != 2:
        return

    token_sets = [
        {match.lower() for match in _DIRECTION_KIND_PATTERN.findall(direction.name)} for direction in route_directions
    ]
    if token_sets.count({"ida"}) != 1 or token_sets.count({"volta"}) != 1:
        return

    for direction, tokens in zip(route_directions, token_sets, strict=True):
        direction.direction_kind = "ida" if tokens == {"ida"} else "volta"


def infer_service_direction_matches(
    service_directions: list[ServiceDirection],
    route_directions: list[RouteDirection],
) -> list[ServiceDirectionMatch]:
    ida_sequence = _find_direction_sequence(route_directions, "ida")
    volta_sequence = _find_direction_sequence(route_directions, "volta")
    services = sorted(service_directions, key=lambda service: service.sequence)

    if ida_sequence is None or volta_sequence is None or len(services) != 2:
        return [_unmatched(service.sequence) for service in services]

    first, second = services
    first_terminal = _looks_like_terminal_departure(first.departure_label)
    second_terminal = _looks_like_terminal_departure(second.departure_label)

    if first_terminal and second_terminal and _normalize(first.departure_label) != _normalize(second.departure_label):
        return [
            _matched(
                first.sequence,
                ida_sequence,
                DirectionMatchConfidence.MEDIUM,
                DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
                {"departure_label": first.departure_label},
            ),
            _matched(
                second.sequence,
                volta_sequence,
                DirectionMatchConfidence.MEDIUM,
                DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
                {"departure_label": second.departure_label},
            ),
        ]

    if first_terminal != second_terminal:
        return [
            _matched(
                first.sequence,
                volta_sequence if first_terminal else ida_sequence,
                DirectionMatchConfidence.MEDIUM,
                DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                {"departure_label": first.departure_label},
            ),
            _matched(
                second.sequence,
                volta_sequence if second_terminal else ida_sequence,
                DirectionMatchConfidence.MEDIUM,
                DirectionMatchMethod.LABEL_ORDER_IDA_VOLTA,
                {"departure_label": second.departure_label},
            ),
        ]

    return [
        _matched(
            first.sequence,
            ida_sequence,
            DirectionMatchConfidence.LOW,
            DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
            {"reason": "first schedule group mapped to ida by observed source order"},
        ),
        _matched(
            second.sequence,
            volta_sequence,
            DirectionMatchConfidence.LOW,
            DirectionMatchMethod.SEQUENCE_IDA_VOLTA,
            {"reason": "second schedule group mapped to volta by observed source order"},
        ),
    ]


def _find_direction_sequence(route_directions: list[RouteDirection], kind: str) -> int | None:
    matching_sequences = [
        sequence for sequence, direction in enumerate(route_directions, start=1) if direction.direction_kind == kind
    ]
    return matching_sequences[0] if len(route_directions) == 2 and len(matching_sequences) == 1 else None


def _looks_like_terminal_departure(label: str) -> bool:
    normalized = _normalize(label)
    return any(token in normalized for token in TERMINAL_TOKENS)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return ascii_value.lower()


def _matched(
    service_sequence: int,
    route_sequence: int,
    confidence: DirectionMatchConfidence,
    method: DirectionMatchMethod,
    notes: dict[str, str],
) -> ServiceDirectionMatch:
    return ServiceDirectionMatch(
        service_direction_sequence=service_sequence,
        route_direction_sequence=route_sequence,
        confidence=confidence,
        method=method,
        notes=notes,
    )


def _unmatched(service_sequence: int) -> ServiceDirectionMatch:
    return ServiceDirectionMatch(service_direction_sequence=service_sequence)
