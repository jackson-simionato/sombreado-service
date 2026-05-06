import logging

from app.config import Settings
from app.logging import configure_logging, get_logger


def test_settings_defaults_use_read_only_advisory_values():
    settings = Settings()

    assert str(settings.database_url) == "postgresql+asyncpg://sombreado_service_reader:sombreado@localhost:5432/consorcio_fenix"
    assert settings.nearby_radius_meters == 100
    assert settings.nearby_limit == 10
    assert settings.off_route_threshold_meters == 75
    assert settings.nominal_bus_speed_kmh == 18


def test_configure_logging_sets_level_and_shared_logger(caplog):
    configure_logging("DEBUG")
    logger = get_logger("app.tests")

    with caplog.at_level(logging.DEBUG):
        logger.debug("route candidate query started")

    assert "route candidate query started" in caplog.text
