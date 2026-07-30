"""Public browser API schemas (camelCase HTTP contract)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from sombreado.domain.schemas import (
    AdviceHorizon,
    AdviceMode,
    ExposureDirection,
    RecommendedSeatArea,
    RouteDirectionKind,
    SunCondition,
)


class BrowserSchema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RouteCandidate(BrowserSchema):
    route_id: UUID
    route_version_id: UUID
    route_code: str
    route_name: str
    direction_hints: list[str] = Field(default_factory=list)
    distance_meters: float | None = None


class RouteCandidatesResponse(BrowserSchema):
    routes: list[RouteCandidate]


class DirectionChoice(BrowserSchema):
    route_direction_id: UUID
    sequence: int
    name: str
    direction_kind: RouteDirectionKind | None
    departure_labels: list[str] = Field(default_factory=list)


class DirectionChoicesResponse(BrowserSchema):
    route_version_id: UUID
    directions: list[DirectionChoice]


RouteDirectionsResponse = DirectionChoicesResponse


class LatLngPoint(BrowserSchema):
    lat: float
    lng: float


class RouteGeometryResponse(BrowserSchema):
    route_id: UUID
    route_version_id: UUID
    route_direction_id: UUID
    polyline: list[LatLngPoint] = Field(default_factory=list)


class AdviceLocation(BrowserSchema):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, ge=0)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_location_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observedAt must be timezone-aware")
        return value


class AdviceRequest(BrowserSchema):
    route_id: str
    route_version_id: str
    route_direction_id: str
    mode: Literal[AdviceMode.onboard, AdviceMode.preview]
    horizon: AdviceHorizon
    observed_at: datetime
    location: AdviceLocation | None = None
    fallback_to_preview: bool = False

    @field_validator("observed_at")
    @classmethod
    def require_observed_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observedAt must be timezone-aware")
        return value


class AdvicePosition(BrowserSchema):
    lat: float
    lng: float
    source: Literal["liveLocation", "directionStart"]
    distance_from_route_meters: float | None = None


class AdviceSuccess(BrowserSchema):
    status: Literal["advice"] = "advice"
    mode: Literal[AdviceMode.onboard, AdviceMode.preview]
    horizon: AdviceHorizon
    route_id: UUID
    route_version_id: UUID
    route_direction_id: UUID
    direct_sun_exposure: ExposureDirection
    recommended_seat_area: RecommendedSeatArea
    sun_condition: SunCondition
    computed_at: datetime
    position: AdvicePosition | None = None


class AdviceWithheld(BrowserSchema):
    status: Literal["withheld"] = "withheld"
    mode: AdviceMode
    horizon: AdviceHorizon | None = None
    route_id: UUID
    route_version_id: UUID
    route_direction_id: UUID
    reason_code: Literal[
        "missingRouteGeometry",
        "insufficientSunSignal",
        "unsupportedDirection",
        "noAdviceForSelectedHorizon",
        "locationOffRoute",
    ]
    computed_at: datetime


AdviceResponse = AdviceSuccess | AdviceWithheld
