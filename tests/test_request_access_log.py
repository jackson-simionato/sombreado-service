import logging
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from sombreado.api.main import create_app
from sombreado.api.request_access_log import (
    classify_response_duration,
    format_request_access_log_message,
)
from sombreado.config import Settings, get_settings


def test_classify_response_duration_uses_agreed_thresholds():
    assert classify_response_duration(0, fast_below_ms=200, slow_at_or_above_ms=1000) == "fast"
    assert classify_response_duration(199.9, fast_below_ms=200, slow_at_or_above_ms=1000) == "fast"
    assert classify_response_duration(200, fast_below_ms=200, slow_at_or_above_ms=1000) == "medium"
    assert classify_response_duration(999.9, fast_below_ms=200, slow_at_or_above_ms=1000) == "medium"
    assert classify_response_duration(1000, fast_below_ms=200, slow_at_or_above_ms=1000) == "slow"


def test_format_request_access_log_message_is_plain_text_without_query():
    message = format_request_access_log_message(
        request_id="11111111-1111-1111-1111-111111111111",
        method="GET",
        path="/v1/routes/nearby",
        status_code=200,
        duration_ms=12.4,
        duration_class="fast",
    )

    assert (
        message == "request_id=11111111-1111-1111-1111-111111111111 method=GET path=/v1/routes/nearby "
        "status=200 duration_ms=12 duration_class=fast"
    )
    assert "?" not in message
    assert "lat=" not in message


def test_settings_default_access_log_duration_thresholds():
    settings = Settings(_env_file=None)

    assert settings.access_log_fast_below_ms == 200
    assert settings.access_log_slow_at_or_above_ms == 1000


@pytest.mark.asyncio
async def test_passenger_api_emits_request_access_log_for_health(caplog, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("ACCESS_LOG_FAST_BELOW_MS", raising=False)
    monkeypatch.delenv("ACCESS_LOG_SLOW_AT_OR_ABOVE_MS", raising=False)
    app = create_app()

    with caplog.at_level(logging.INFO):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health/live")

    assert response.status_code == 200
    access_records = [record for record in caplog.records if "duration_class=" in record.getMessage()]
    assert len(access_records) == 1
    assert access_records[0].levelno == logging.INFO
    message = access_records[0].getMessage()
    assert "method=GET" in message
    assert "path=/health/live" in message
    assert "status=200" in message
    assert "duration_ms=" in message
    assert "duration_class=" in message
    assert "duration_class=slow" not in message
    assert "request_id=" in message
    request_id = message.split("request_id=", 1)[1].split(" ", 1)[0]
    UUID(request_id)


@pytest.mark.asyncio
async def test_request_access_log_omits_query_string(caplog, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("ACCESS_LOG_FAST_BELOW_MS", raising=False)
    monkeypatch.delenv("ACCESS_LOG_SLOW_AT_OR_ABOVE_MS", raising=False)
    app = create_app()

    with caplog.at_level(logging.INFO):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/health/live", params={"lat": "-27.6", "lng": "-48.5"})

    access_records = [record for record in caplog.records if "duration_class=" in record.getMessage()]
    assert len(access_records) == 1
    message = access_records[0].getMessage()
    assert "path=/health/live" in message
    assert "lat=" not in message
    assert "lng=" not in message
    assert "?" not in message


@pytest.mark.asyncio
async def test_slow_request_access_log_uses_warning(caplog, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("ACCESS_LOG_FAST_BELOW_MS", "0")
    monkeypatch.setenv("ACCESS_LOG_SLOW_AT_OR_ABOVE_MS", "0")
    app = create_app()

    with caplog.at_level(logging.INFO):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/health/live")

    access_records = [record for record in caplog.records if "duration_class=slow" in record.getMessage()]
    assert len(access_records) == 1
    assert access_records[0].levelno == logging.WARNING


@pytest.mark.asyncio
async def test_unexpected_error_log_shares_request_id_with_access_log(caplog, monkeypatch):
    from sombreado.api.routes.route_candidates import get_route_service as get_route_candidate_service

    get_settings.cache_clear()
    monkeypatch.delenv("ACCESS_LOG_FAST_BELOW_MS", raising=False)
    monkeypatch.delenv("ACCESS_LOG_SLOW_AT_OR_ABOVE_MS", raising=False)
    app = create_app()

    class ExplodingRouteCandidateService:
        async def search_route_candidates(self, *, query, limit):
            raise RuntimeError("boom")

    async def exploding_service():
        return ExplodingRouteCandidateService()

    app.dependency_overrides[get_route_candidate_service] = exploding_service

    with caplog.at_level(logging.INFO):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/v1/route-candidates/search", params={"query": "330"})

    assert response.status_code == 503
    access_records = [record for record in caplog.records if "duration_class=" in record.getMessage()]
    error_records = [record for record in caplog.records if "Unhandled public API exception" in record.getMessage()]
    assert len(access_records) == 1
    assert len(error_records) == 1
    access_request_id = access_records[0].getMessage().split("request_id=", 1)[1].split(" ", 1)[0]
    assert f"request_id={access_request_id}" in error_records[0].getMessage()
    assert "status=503" in access_records[0].getMessage()
    assert "path=/v1/route-candidates/search" in access_records[0].getMessage()
    assert "query=" not in access_records[0].getMessage()
