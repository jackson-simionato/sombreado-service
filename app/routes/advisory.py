from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings_dependency
from app.db import get_session
from app.errors import PublicApiError, parse_public_uuid
from app.schemas import (
    AdviceComputationRequest,
    AdviceMode,
    AdviceRequest,
    AdviceResponse,
    OnboardAdvisoryRequest,
    OnboardAdvisoryResponse,
)
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


@router.post("/advice", response_model=AdviceResponse, response_model_exclude_none=True)
async def advice(
    request: AdviceRequest,
    advisory_service: Annotated[AdvisoryService, Depends(get_advisory_service)],
) -> AdviceResponse:
    if request.mode is AdviceMode.onboard:
        raise PublicApiError(
            status_code=422,
            code="validationFailed",
            message="Onboard advice is not implemented yet.",
        )
    if request.location is not None:
        raise PublicApiError(
            status_code=422,
            code="validationFailed",
            message="Preview advice must not include location.",
        )

    parsed_request = AdviceComputationRequest(
        route_id=parse_public_uuid(request.route_id),
        route_version_id=parse_public_uuid(request.route_version_id),
        route_direction_id=parse_public_uuid(request.route_direction_id),
        mode=request.mode,
        horizon=request.horizon,
        observed_at=request.observed_at,
        location=request.location,
        fallback_to_preview=request.fallback_to_preview,
    )
    return await advisory_service.build_advice(parsed_request)
