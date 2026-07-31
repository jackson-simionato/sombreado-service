"""Consórcio catalogue source: absence vs hard failure of still-listed routes."""

from __future__ import annotations

import pytest

from sombreado.ingestion.catalogue import ConsorcioCatalogueSource
from sombreado.ingestion.domain import ParsedRoutePage
from sombreado.ingestion.http import FetcherConfig

INDEX = "https://example.test/horarios"
ROUTE_A = "https://example.test/horarios/a,110"
ROUTE_B = "https://example.test/horarios/b,120"

INDEX_HTML = f"""
<html><body>
<a href="{ROUTE_A}">A</a>
<a href="{ROUTE_B}">B</a>
</body></html>
"""

ROUTE_HTML = "<html><body>route</body></html>"


class FakeFetcher:
    def __init__(self, pages: dict[str, str | Exception]) -> None:
        self.pages = pages
        self.config = FetcherConfig(retries=0, rate_limit_seconds=0)

    async def get_text(self, url: str) -> str:
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value

    async def close(self) -> None:
        return None


def _parsed(page_url: str, code: str) -> ParsedRoutePage:
    return ParsedRoutePage(
        code=code,
        name=f"Route {code}",
        slug=f"route-{code}",
        page_url=page_url,
        map_url=None,
    )


@pytest.mark.asyncio
async def test_still_listed_fetch_failure_is_hard_failure(monkeypatch):
    source = ConsorcioCatalogueSource(source_url=INDEX, concurrency=1)
    pages: dict[str, str | Exception] = {
        INDEX: INDEX_HTML,
        ROUTE_A: RuntimeError("boom"),
        ROUTE_B: ROUTE_HTML,
    }
    monkeypatch.setattr(
        "sombreado.ingestion.catalogue.AsyncHttpFetcher",
        lambda _config=None: FakeFetcher(pages),
    )
    monkeypatch.setattr(
        "sombreado.ingestion.catalogue.parse_route_page",
        lambda html, page_url: _parsed(page_url, "120" if ROUTE_B in page_url else "110"),
    )
    monkeypatch.setattr(
        "sombreado.ingestion.catalogue.infer_service_direction_matches",
        lambda *_args, **_kwargs: [],
    )
    warnings_logged: list[str] = []

    def capture_warning(message: str, *args: object) -> None:
        warnings_logged.append(message % args if args else message)

    monkeypatch.setattr("sombreado.ingestion.catalogue.logger.warning", capture_warning)

    collection = await source._collect_async()

    assert ROUTE_A in collection.hard_failures
    assert collection.rows["routes"] == []
    assert any("RuntimeError: boom" in message for message in warnings_logged)


@pytest.mark.asyncio
async def test_missing_snapshot_without_error_is_hard_failure(monkeypatch):
    source = ConsorcioCatalogueSource(source_url=INDEX, concurrency=1)
    pages: dict[str, str | Exception] = {INDEX: INDEX_HTML, ROUTE_A: ROUTE_HTML, ROUTE_B: ROUTE_HTML}
    monkeypatch.setattr(
        "sombreado.ingestion.catalogue.AsyncHttpFetcher",
        lambda _config=None: FakeFetcher(pages),
    )

    async def fake_fetch_one(self, fetcher, semaphore, index, total, route_url):
        del self, fetcher, semaphore, total
        return index, route_url, None, None, ()

    monkeypatch.setattr(ConsorcioCatalogueSource, "_fetch_one", fake_fetch_one)

    collection = await source._collect_async()

    assert ROUTE_A in collection.hard_failures
    assert ROUTE_B in collection.hard_failures
    assert collection.rows["routes"] == []


@pytest.mark.asyncio
async def test_catalogue_absence_omits_route_without_hard_failure(monkeypatch):
    source = ConsorcioCatalogueSource(source_url=INDEX, concurrency=1)
    index_only_a = f'<html><body><a href="{ROUTE_A}">A</a></body></html>'
    pages: dict[str, str | Exception] = {INDEX: index_only_a, ROUTE_A: ROUTE_HTML}
    monkeypatch.setattr(
        "sombreado.ingestion.catalogue.AsyncHttpFetcher",
        lambda _config=None: FakeFetcher(pages),
    )
    monkeypatch.setattr(
        "sombreado.ingestion.catalogue.parse_route_page",
        lambda html, page_url: _parsed(page_url, "110"),
    )
    monkeypatch.setattr(
        "sombreado.ingestion.catalogue.infer_service_direction_matches",
        lambda *_args, **_kwargs: [],
    )

    collection = await source._collect_async()

    assert collection.hard_failures == ()
    assert len(collection.rows["routes"]) == 1
    assert collection.rows["routes"][0]["code"] == "110"
    assert any("map unavailable" in warning for warning in collection.warnings)
