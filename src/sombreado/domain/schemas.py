"""Shared domain DTOs and enums (not the public browser HTTP schemas)."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ExposureDirection(StrEnum):
    left = "left"
    right = "right"
    front = "front"
    back = "back"
    overhead = "overhead"
    none = "none"


class RecommendedSeatArea(StrEnum):
    left = "left"
    right = "right"
    front = "front"
    back = "back"
    neutral = "neutral"


class SunCondition(StrEnum):
    daylight = "daylight"
    night = "night"
    low_sun = "lowSun"
    overhead = "overhead"


class AdviceMode(StrEnum):
    onboard = "onboard"
    preview = "preview"
    unavailable = "unavailable"


class AdviceHorizon(StrEnum):
    upcoming = "upcoming"
    remaining_route = "remainingRoute"


class RouteDirectionKind(StrEnum):
    ida = "ida"
    volta = "volta"


class SunPosition(BaseModel):
    azimuth: float = Field(ge=0, le=360)
    elevation: float


class RouteCandidate(BaseModel):
    route_id: UUID
    route_version_id: UUID
    route_code: str
    route_name: str
    direction_hints: list[str] = Field(default_factory=list)
    distance_meters: float | None = None


class LightweightRouteDirection(BaseModel):
    route_direction_id: UUID
    sequence: int
    name: str
    departure_labels: list[str] = Field(default_factory=list)


class DirectionChoice(BaseModel):
    route_direction_id: UUID
    sequence: int
    name: str
    direction_kind: RouteDirectionKind | None
    departure_labels: list[str] = Field(default_factory=list)


class RouteSummary(BaseModel):
    route_id: UUID
    route_code: str
    route_name: str
    route_version_id: UUID
    directions: list[LightweightRouteDirection] = Field(default_factory=list)
    distance_meters: float | None = None


class RoutesResponse(BaseModel):
    routes: list[RouteSummary]


class CandidateRouteDirection(BaseModel):
    route_id: UUID
    route_code: str
    route_name: str
    route_version_id: UUID
    route_direction_id: UUID
    route_direction_sequence: int
    route_direction_name: str
    departure_labels: list[str] = Field(default_factory=list)
    distance_meters: float


class NearbyRouteDirectionsResponse(BaseModel):
    candidates: list[CandidateRouteDirection]


class RouteSegment(BaseModel):
    id: UUID
    sequence: int
    coordinates: list[tuple[float, float]]
    bearing_degrees: float
    distance_meters: float
    cumulative_distance_meters: float


class LatLngPoint(BaseModel):
    lat: float
    lng: float


class AdviceLocation(BaseModel):
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


class AdviceComputationRequest(BaseModel):
    route_id: UUID
    route_version_id: UUID
    route_direction_id: UUID
    mode: Literal[AdviceMode.onboard, AdviceMode.preview]
    horizon: AdviceHorizon
    observed_at: datetime
    location: AdviceLocation | None = None
    fallback_to_preview: bool = False


class AdvicePosition(BaseModel):
    lat: float
    lng: float
    source: Literal["liveLocation", "directionStart"]
    distance_from_route_meters: float | None = None


class AdviceSuccess(BaseModel):
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


class AdviceWithheld(BaseModel):
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


class SegmentForAdvice(BaseModel):
    segment_id: UUID
    sequence: int
    midpoint_lat: float
    midpoint_lng: float
    bearing_degrees: float
    distance_meters: float
    cumulative_distance_meters: float


class ProjectedRoutePosition(BaseModel):
    segment_id: UUID
    segment_sequence: int
    lat: float
    lng: float
    distance_from_route_meters: float
    cumulative_distance_meters: float


class ExposureWindow(BaseModel):
    total_distance_meters: float
    dominant_direction: ExposureDirection
    breakdown_meters: dict[ExposureDirection, float]


class OnboardAdviceRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    route_version_id: UUID
    route_direction_id: UUID
    datetime: datetime
    window_minutes: int = Field(default=15, gt=0, le=180)
    include_remaining: bool = True

    @field_validator("datetime")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value


class OnboardAdviceResponse(BaseModel):
    status: Literal["advisory", "withheld"]
    route_version_id: UUID
    route_direction_id: UUID
    requested_at: datetime
    projected_position: ProjectedRoutePosition | None = None
    upcoming_window: ExposureWindow | None = None
    remaining_route: ExposureWindow | None = None
    reason: str | None = None
