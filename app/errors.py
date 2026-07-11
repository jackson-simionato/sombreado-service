from uuid import UUID

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logging import get_logger

logger = get_logger(__name__)


class PublicError(BaseModel):
    code: str
    message: str | None = None


class PublicErrorEnvelope(BaseModel):
    error: PublicError


class PublicApiError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message


def public_error_response(*, status_code: int, code: str, message: str | None = None) -> JSONResponse:
    envelope = PublicErrorEnvelope(error=PublicError(code=code, message=message))
    return JSONResponse(status_code=status_code, content=envelope.model_dump(exclude_none=True))


def parse_public_uuid(value: str, *, message: str = "Request validation failed.") -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise PublicApiError(status_code=422, code="validationFailed", message=message) from exc


async def public_api_error_handler(_request: Request, exc: PublicApiError) -> JSONResponse:
    return public_error_response(status_code=exc.status_code, code=exc.code, message=exc.message)


async def validation_exception_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return public_error_response(
        status_code=422,
        code="validationFailed",
        message="Request validation failed.",
    )


async def unexpected_public_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if request.url.path.startswith("/v1"):
        logger.exception("Unhandled public API exception for %s", request.url.path, exc_info=exc)
        return public_error_response(
            status_code=503,
            code="serviceUnavailable",
            message="Service temporarily unavailable.",
        )
    raise exc
