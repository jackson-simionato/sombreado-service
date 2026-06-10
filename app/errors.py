from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class PublicError(BaseModel):
    code: str
    message: str | None = None


class PublicErrorEnvelope(BaseModel):
    error: PublicError


def public_error_response(*, status_code: int, code: str, message: str | None = None) -> JSONResponse:
    envelope = PublicErrorEnvelope(error=PublicError(code=code, message=message))
    return JSONResponse(status_code=status_code, content=envelope.model_dump(exclude_none=True))


async def validation_exception_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return public_error_response(
        status_code=422,
        code="validationFailed",
        message="Request validation failed.",
    )
