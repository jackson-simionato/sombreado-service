from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings_dependency
from app.db import get_session
from app.schemas import RouteCandidatesResponse
from app.services.routes import RouteReadService

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
