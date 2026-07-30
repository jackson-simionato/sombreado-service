from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from sombreado.api.deps import get_session, get_settings_dependency
from sombreado.api.schemas import RouteCandidatesResponse
from sombreado.config import Settings
from sombreado.route_reads.service import RouteReadService

router = APIRouter(prefix="/v1/route-candidates", tags=["route-candidates"])


async def get_route_service(session: Annotated[AsyncSession, Depends(get_session)]) -> RouteReadService:
    return RouteReadService(session)


@router.get("/search", response_model=RouteCandidatesResponse, response_model_exclude_none=True)
async def search_route_candidates(
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    query: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int | None, Query(gt=0, le=100)] = None,
) -> RouteCandidatesResponse:
    routes = await route_service.search_route_candidates(
        query=query,
        limit=limit or settings.route_candidate_search_limit,
    )
    return RouteCandidatesResponse(routes=routes)


@router.get("/nearby", response_model=RouteCandidatesResponse, response_model_exclude_none=True)
async def nearby_route_candidates(
    route_service: Annotated[RouteReadService, Depends(get_route_service)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    radius_meters: Annotated[float | None, Query(alias="radiusMeters", gt=0, le=2000)] = None,
    limit: Annotated[int | None, Query(gt=0, le=100)] = None,
) -> RouteCandidatesResponse:
    routes = await route_service.find_nearby_route_candidates(
        lat=lat,
        lng=lng,
        radius_meters=radius_meters or settings.route_candidate_nearby_radius_meters,
        limit=limit or settings.route_candidate_nearby_limit,
    )
    return RouteCandidatesResponse(routes=routes)
