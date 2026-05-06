from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings_dependency
from app.db import get_session
from app.schemas import NearbyRouteDirectionsResponse
from app.services.routes import RouteReadService

router = APIRouter(prefix="/v1", tags=["routes"])


async def get_route_service(session: Annotated[AsyncSession, Depends(get_session)]) -> RouteReadService:
    return RouteReadService(session)


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
