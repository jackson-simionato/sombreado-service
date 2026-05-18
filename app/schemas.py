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


class SunPosition(BaseModel):
    azimuth: float = Field(ge=0, le=360)
    elevation: float


class LightweightRouteDirection(BaseModel):
    route_direction_id: UUID
    sequence: int
    name: str
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


class RouteDirectionsResponse(BaseModel):
    directions: list[LightweightRouteDirection]


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


class RouteGeometryResponse(BaseModel):
    route_version_id: UUID
    route_direction_id: UUID
    segments: list[RouteSegment]


class SegmentForAdvisory(BaseModel):
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


class OnboardAdvisoryRequest(BaseModel):
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


class OnboardAdvisoryResponse(BaseModel):
    status: Literal["advisory", "withheld"]
    route_version_id: UUID
    route_direction_id: UUID
    requested_at: datetime
    projected_position: ProjectedRoutePosition | None = None
    upcoming_window: ExposureWindow | None = None
    remaining_route: ExposureWindow | None = None
    reason: str | None = None
