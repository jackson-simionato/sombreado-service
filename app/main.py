from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.logging import configure_logging
from app.routes import advisory, health, nearby


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="sombreado-service")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(health.router)
    app.include_router(nearby.router)
    app.include_router(advisory.router)
    return app


app = create_app()
