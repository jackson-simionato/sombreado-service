from uuid import UUID

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sombreado.api.request_access_log import REQUEST_ID_STATE_KEY
from sombreado.domain.errors import ServiceError
from sombreado.logging import get_logger

logger = get_logger(__name__)

_STATUS_BY_CODE = {
    "validationFailed": 422,
    "routeNotFound": 404,
    "routeDirectionNotFound": 404,
    "routeVersionStale": 409,
    "serviceUnavailable": 503,
}


class PublicApiError(ServiceError):
    """HTTP-boundary error with an explicit status code."""

    def __init__(self, *, status_code: int, code: str, message: str | None = None):
        super().__init__(code=code, message=message)
        self.status_code = status_code


__all__ = [
    "PublicApiError",
    "parse_public_uuid",
    "public_api_error_handler",
    "public_error_response",
    "status_code_for_service_error",
    "unexpected_public_error_handler",
    "validation_exception_handler",
]


class PublicError(BaseModel):
    code: str
    message: str | None = None


class PublicErrorEnvelope(BaseModel):
    error: PublicError


def status_code_for_service_error(exc: ServiceError) -> int:
    if isinstance(exc, PublicApiError):
        return exc.status_code
    return _STATUS_BY_CODE.get(exc.code, 500)


def public_error_response(*, status_code: int, code: str, message: str | None = None) -> JSONResponse:
    envelope = PublicErrorEnvelope(error=PublicError(code=code, message=message))
    return JSONResponse(status_code=status_code, content=envelope.model_dump(exclude_none=True))


def parse_public_uuid(value: str, *, message: str = "Request validation failed.") -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise PublicApiError(status_code=422, code="validationFailed", message=message) from exc


async def public_api_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
    return public_error_response(
        status_code=status_code_for_service_error(exc),
        code=exc.code,
        message=exc.message,
    )


async def validation_exception_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return public_error_response(
        status_code=422,
        code="validationFailed",
        message="Request validation failed.",
    )


async def unexpected_public_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if request.url.path.startswith("/v1"):
        request_id = getattr(request.state, REQUEST_ID_STATE_KEY, None)
        logger.exception(
            "Unhandled public API exception request_id=%s path=%s",
            request_id,
            request.url.path,
            exc_info=exc,
        )
        return public_error_response(
            status_code=503,
            code="serviceUnavailable",
            message="Service temporarily unavailable.",
        )
    raise exc
