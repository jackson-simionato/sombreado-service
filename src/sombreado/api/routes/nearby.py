from typing import Annotated

from fastapi import APIRouter, Depends, Query

from sombreado.api.deps import get_current_route_service
from sombreado.api.errors import PublicApiError, parse_public_uuid
from sombreado.api.mapping import to_direction_choices, to_polyline
from sombreado.api.schemas import (
    RouteDirectionsResponse,
    RouteGeometryResponse,
)
from sombreado.domain.geometry import flatten_route_polyline
from sombreado.route_reads.current import CurrentRouteReadService

router = APIRouter(prefix="/v1", tags=["routes"])

# Re-export for tests that override the passenger-read dependency by this name.
get_discovery_service = get_current_route_service
get_route_service = get_current_route_service


@router.get("/routes/{route_id}/directions", response_model=RouteDirectionsResponse)
async def route_directions(
    route_id: str,
    route_service: Annotated[CurrentRouteReadService, Depends(get_current_route_service)],
    route_version_id_text: Annotated[str | None, Query(alias="routeVersionId")] = None,
) -> RouteDirectionsResponse:
    parsed_route_id = parse_public_uuid(route_id)
    route_version_id = parse_public_uuid(route_version_id_text) if route_version_id_text is not None else None
    current_route_version_id = await route_service.load_current_route_version_id(parsed_route_id)
    if current_route_version_id is None:
        raise PublicApiError(status_code=404, code="routeNotFound", message="Current route was not found.")
    if route_version_id is not None and current_route_version_id != route_version_id:
        raise PublicApiError(
            status_code=409,
            code="routeVersionStale",
            message="Selected route version is no longer current.",
        )
    directions = await route_service.load_direction_choices(route_version_id=current_route_version_id)
    return RouteDirectionsResponse(
        route_version_id=current_route_version_id,
        directions=to_direction_choices(directions),
    )


@router.get(
    "/routes/{route_id}/directions/{route_direction_id}/geometry",
    response_model=RouteGeometryResponse,
)
async def route_geometry(
    route_id: str,
    route_direction_id: str,
    route_service: Annotated[CurrentRouteReadService, Depends(get_current_route_service)],
    route_version_id_text: Annotated[str, Query(alias="routeVersionId")],
) -> RouteGeometryResponse:
    parsed_route_id = parse_public_uuid(route_id)
    parsed_route_direction_id = parse_public_uuid(route_direction_id)
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
    if not await route_service.route_direction_belongs_to_version(
        route_version_id=route_version_id,
        route_direction_id=parsed_route_direction_id,
    ):
        raise PublicApiError(
            status_code=404,
            code="routeDirectionNotFound",
            message="Current route direction was not found.",
        )

    segments = await route_service.load_current_route_segments(
        route_version_id=route_version_id,
        route_direction_id=parsed_route_direction_id,
    )
    return RouteGeometryResponse(
        route_id=parsed_route_id,
        route_version_id=route_version_id,
        route_direction_id=parsed_route_direction_id,
        polyline=to_polyline(flatten_route_polyline(segments)),
    )
