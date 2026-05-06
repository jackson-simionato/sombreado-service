from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings_dependency
from app.db import get_session
from app.schemas import OnboardAdvisoryRequest, OnboardAdvisoryResponse
from app.services.advisory import AdvisoryService
from app.services.routes import RouteReadService

router = APIRouter(prefix="/v1", tags=["advisory"])


async def get_advisory_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> AdvisoryService:
    return AdvisoryService(route_service=RouteReadService(session), settings=settings)


@router.post("/onboard-advisories", response_model=OnboardAdvisoryResponse)
async def onboard_advisory(
    request: OnboardAdvisoryRequest,
    advisory_service: Annotated[AdvisoryService, Depends(get_advisory_service)],
) -> OnboardAdvisoryResponse:
    return await advisory_service.build_onboard_advisory(request)
