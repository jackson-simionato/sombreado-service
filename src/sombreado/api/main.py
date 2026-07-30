from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from sombreado.api.errors import (
    PublicApiError,
    public_api_error_handler,
    unexpected_public_error_handler,
    validation_exception_handler,
)
from sombreado.api.routes import advisory, health, nearby, route_candidates
from sombreado.config import get_settings
from sombreado.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="sombreado-service")
    app.add_exception_handler(PublicApiError, public_api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unexpected_public_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(health.router)
    app.include_router(route_candidates.router)
    app.include_router(nearby.router)
    app.include_router(advisory.router)
    return app


app = create_app()
