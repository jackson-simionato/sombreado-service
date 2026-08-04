"""Map domain DTOs to public browser schemas."""

from collections.abc import Mapping, Sequence
from typing import Any

from sombreado.api.schemas import (
    AdviceSuccess,
    AdviceWithheld,
    DirectionChoice,
    LatLngPoint,
    RouteCandidate,
)
from sombreado.domain.schemas import AdviceResponse as DomainAdviceResponse
from sombreado.domain.schemas import DirectionChoice as DomainDirectionChoice
from sombreado.domain.schemas import LatLngPoint as DomainLatLngPoint
from sombreado.domain.schemas import RouteCandidate as DomainRouteCandidate


def to_route_candidates(routes: Sequence[DomainRouteCandidate]) -> list[RouteCandidate]:
    return [RouteCandidate.model_validate(route, from_attributes=True) for route in routes]


def to_direction_choices(directions: Sequence[DomainDirectionChoice]) -> list[DirectionChoice]:
    return [DirectionChoice.model_validate(direction, from_attributes=True) for direction in directions]


def to_polyline(points: Sequence[DomainLatLngPoint]) -> list[LatLngPoint]:
    return [LatLngPoint.model_validate(point, from_attributes=True) for point in points]


def to_advice_response(result: DomainAdviceResponse | Mapping[str, Any]) -> AdviceSuccess | AdviceWithheld:
    payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    if payload.get("status") == "withheld":
        return AdviceWithheld.model_validate(payload)
    return AdviceSuccess.model_validate(payload)
