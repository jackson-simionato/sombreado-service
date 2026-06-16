import logging

from app.config import Settings
from app.logging import configure_logging, get_logger


def test_settings_defaults_use_read_only_advisory_values():
    settings = Settings(_env_file=None)

    assert (
        str(settings.database_url)
        == "postgresql+asyncpg://sombreado_service_reader:sombreado@localhost:5432/consorcio_fenix"
    )
    assert settings.nearby_radius_meters == 100
    assert settings.nearby_limit == 10
    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"]
    assert settings.route_candidate_nearby_radius_meters == 1200
    assert settings.route_candidate_nearby_limit == 5
    assert settings.route_candidate_search_limit == 8
    assert settings.off_route_threshold_meters == 75
    assert settings.nominal_bus_speed_kmh == 18


def test_cors_origins_can_be_configured_from_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["https://app.example.com"]


def test_configure_logging_sets_level_and_shared_logger(caplog):
    configure_logging("DEBUG")
    logger = get_logger("app.tests")

    with caplog.at_level(logging.DEBUG):
        logger.debug("route candidate query started")

    assert "route candidate query started" in caplog.text
