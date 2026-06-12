from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings_dependency
from app.db import get_session
from app.errors import PublicApiError, parse_public_uuid
from app.schemas import (
    NearbyRouteDirectionsResponse,
    RouteDirectionsResponse,
    RouteGeometryResponse,
    RoutesResponse,
    RouteSummary,
)
from app.services.routes import RouteReadService

router = APIRouter(prefix="/v1", tags=["routes"])


async def get_route_service(session: Annotated[AsyncSession, Depends(get_session)]) -> RouteReadService:
    return RouteReadService(session)


@router.get("/routes", response_model=RoutesResponse)
async def list_routes(
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    query: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_meters: Annotated[float | None, Query(gt=0, le=2000)] = None,
    limit: Annotated[int | None, Query(gt=0, le=100)] = None,
) -> RoutesResponse:
    location_values = (lat, lng, radius_meters)
    has_location = lat is not None and lng is not None
    if any(value is not None for value in location_values) and not has_location:
        raise HTTPException(status_code=422, detail="lat, lng, and radius_meters must be provided together")

    resolved_radius_meters = radius_meters
    if has_location and resolved_radius_meters is None:
        resolved_radius_meters = settings.nearby_radius_meters

    routes = await route_service.list_current_routes(
        query=query,
        lat=lat,
        lng=lng,
        radius_meters=resolved_radius_meters,
        limit=limit or settings.nearby_limit,
    )
    return RoutesResponse(routes=routes)


@router.get("/routes/{route_id}", response_model=RouteSummary)
async def route_detail(
    route_id: UUID,
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
) -> RouteSummary:
    route = await route_service.load_current_route(route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="current route not found")
    return route


@router.get("/routes/{route_id}/directions", response_model=RouteDirectionsResponse)
async def route_directions(
    route_id: str,
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    route_version_id_text: Annotated[str, Query(alias="routeVersionId")],
) -> RouteDirectionsResponse:
    parsed_route_id = parse_public_uuid(route_id)
    route_version_id = parse_public_uuid(route_version_id_text)
    current_route_version_id = await route_service.load_current_route_version_id(parsed_route_id)
    if current_route_version_id is None:
        raise PublicApiError(status_code=404, code="routeNotFound", message="Current route was not found.")
    if current_route_version_id != route_version_id:
        raise PublicApiError(
            status_code=409,
            code="routeVersionStale",
            message="Selected route version is no longer current.",
        )
    directions = await route_service.load_direction_choices(route_version_id=route_version_id)
    return RouteDirectionsResponse(directions=directions)


@router.get("/route-directions/{route_direction_id}/segments", response_model=RouteGeometryResponse)
async def route_direction_segments(
    route_direction_id: UUID,
    route_version_id: Annotated[UUID, Query()],
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
) -> RouteGeometryResponse:
    segments = await route_service.load_current_route_segments(
        route_version_id=route_version_id,
        route_direction_id=route_direction_id,
    )
    if not segments:
        raise HTTPException(status_code=404, detail="current route direction geometry not found")
    return RouteGeometryResponse(
        route_version_id=route_version_id,
        route_direction_id=route_direction_id,
        segments=segments,
    )


@router.get("/nearby-route-directions", response_model=NearbyRouteDirectionsResponse)
async def nearby_route_directions(
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    radius_meters: Annotated[float | None, Query(gt=0, le=2000)] = None,
    limit: Annotated[int | None, Query(gt=0, le=100)] = None,
) -> NearbyRouteDirectionsResponse:
    candidates = await route_service.find_nearby_route_directions(
        lat=lat,
        lng=lng,
        radius_meters=radius_meters or settings.nearby_radius_meters,
        limit=limit or settings.nearby_limit,
    )
    return NearbyRouteDirectionsResponse(candidates=candidates)
