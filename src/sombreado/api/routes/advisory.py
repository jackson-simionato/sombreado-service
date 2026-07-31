from typing import Annotated

from fastapi import APIRouter, Depends

from sombreado.advice.service import AdviceService
from sombreado.api.deps import get_current_route_service, get_settings_dependency
from sombreado.api.errors import PublicApiError, parse_public_uuid
from sombreado.api.mapping import to_advice_response
from sombreado.api.schemas import AdviceRequest, AdviceResponse
from sombreado.config import Settings
from sombreado.domain.schemas import AdviceComputationRequest, AdviceLocation, AdviceMode
from sombreado.route_reads.current import CurrentRouteReadService

router = APIRouter(prefix="/v1", tags=["advisory"])


async def get_advisory_service(
    route_service: Annotated[CurrentRouteReadService, Depends(get_current_route_service)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> AdviceService:
    return AdviceService(route_service=route_service, settings=settings)


@router.post("/advice", response_model=AdviceResponse, response_model_exclude_none=True)
async def advice(
    request: AdviceRequest,
    advisory_service: Annotated[AdviceService, Depends(get_advisory_service)],
) -> AdviceResponse:
    if request.mode is AdviceMode.onboard and request.location is None:
        raise PublicApiError(
            status_code=422,
            code="validationFailed",
            message="Onboard advice requires location.",
        )
    if request.mode is AdviceMode.preview and request.location is not None:
        raise PublicApiError(
            status_code=422,
            code="validationFailed",
            message="Preview advice must not include location.",
        )

    location = None
    if request.location is not None:
        location = AdviceLocation.model_validate(request.location, from_attributes=True)

    parsed_request = AdviceComputationRequest(
        route_id=parse_public_uuid(request.route_id),
        route_version_id=parse_public_uuid(request.route_version_id),
        route_direction_id=parse_public_uuid(request.route_direction_id),
        mode=request.mode,
        horizon=request.horizon,
        observed_at=request.observed_at,
        location=location,
        fallback_to_preview=request.fallback_to_preview,
    )
    return to_advice_response(await advisory_service.build_advice(parsed_request))
