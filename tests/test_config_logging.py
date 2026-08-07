import logging

import pytest

from sombreado.config import Settings, get_api_settings, get_cli_settings, get_settings
from sombreado.logging import configure_logging, get_logger


def test_settings_defaults_use_passenger_api_values(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = Settings(_env_file=None)

    assert settings.database_url == ""
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


def test_api_and_cli_settings_reject_empty_database_url():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(_env_file=None, database_url="").require_api()
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(_env_file=None, database_url="   ").require_cli()


def test_api_and_cli_settings_accept_database_url(monkeypatch, database_url: str):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert get_api_settings().database_url == database_url
    assert get_cli_settings().database_url == database_url


def test_settings_ignore_unknown_neon_env_pull_extras(monkeypatch, database_url: str):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("NEON_BRANCH", "production")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url == database_url
    assert not hasattr(settings, "neon_branch")


def test_api_settings_reject_empty_cors_origins(database_url: str):
    settings = Settings(_env_file=None, database_url=database_url, cors_origins=[])

    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        settings.require_api()


def test_configure_logging_sets_level_and_shared_logger(caplog):
    configure_logging("DEBUG")
    logger = get_logger("sombreado.tests")

    with caplog.at_level(logging.DEBUG):
        logger.debug("route candidate query started")

    assert "route candidate query started" in caplog.text
