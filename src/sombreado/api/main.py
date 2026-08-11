from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import Receive, Scope, Send

from sombreado.api.errors import (
    public_api_error_handler,
    unexpected_public_error_handler,
    validation_exception_handler,
)
from sombreado.api.request_access_log import RequestAccessLogMiddleware
from sombreado.api.routes import advisory, health, nearby, route_candidates
from sombreado.config import get_api_settings, get_settings
from sombreado.domain.errors import ServiceError
from sombreado.logging import configure_logging, get_logger
from sombreado.store import GenerationStore, redacted_database_url


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_api_settings()
    store = GenerationStore(settings.database_url)
    store.migrate()
    get_logger(__name__).info(
        "Applied Generation Store migrations database=%s current=%s",
        redacted_database_url(settings.database_url),
        store.current_generation(),
    )
    yield


class AccessLoggedAPI(FastAPI):
    """FastAPI app with Request Access Log outside ServerErrorMiddleware."""

    def __init__(
        self,
        *,
        access_log_fast_below_ms: float,
        access_log_slow_at_or_above_ms: float,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._request_access_log = RequestAccessLogMiddleware(
            self._call_fastapi,
            fast_below_ms=access_log_fast_below_ms,
            slow_at_or_above_ms=access_log_slow_at_or_above_ms,
        )

    async def _call_fastapi(self, scope: Scope, receive: Receive, send: Send) -> None:
        await super().__call__(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._request_access_log(scope, receive, send)


def create_app() -> FastAPI:
    # CORS/logging may load before DATABASE_URL is set (module import / test setup).
    # Lifespan and deps call get_api_settings() and require a non-empty DATABASE_URL.
    settings = get_settings()
    configure_logging(settings.log_level)

    app = AccessLoggedAPI(
        title="sombreado-service",
        lifespan=lifespan,
        access_log_fast_below_ms=settings.access_log_fast_below_ms,
        access_log_slow_at_or_above_ms=settings.access_log_slow_at_or_above_ms,
    )
    app.add_exception_handler(ServiceError, public_api_error_handler)
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
