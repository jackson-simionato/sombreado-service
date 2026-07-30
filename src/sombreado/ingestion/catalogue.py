"""Live Consórcio Fênix catalogue fetch → ScrapeCollection."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sombreado.ingestion.canonical import hash_text, snapshots_to_canonical_rows
from sombreado.ingestion.directions import infer_service_direction_matches
from sombreado.ingestion.domain import DirectionMatchConfidence, RouteSnapshot
from sombreado.ingestion.http import AsyncHttpFetcher, FetcherConfig, limited, parse_route_links
from sombreado.ingestion.parsers.kml import extract_kml, parse_kml_directions
from sombreado.ingestion.parsers.route_page import parse_route_page
from sombreado.ingestion.scrape import ScrapeCollection

logger = logging.getLogger(__name__)

DEFAULT_ROUTE_INDEX_URL = "https://www.consorciofenix.com.br/horarios"

_EMPTY_ROWS = {
    "routes": [],
    "route_versions": [],
    "route_directions": [],
    "service_directions": [],
    "route_segments": [],
}


@dataclass(frozen=True)
class ConsorcioCatalogueSource:
    """Fetch the live Consórcio catalogue; hard-fail still-listed routes that break."""

    source_url: str = DEFAULT_ROUTE_INDEX_URL
    concurrency: int = 4
    limit: int | None = None
    fetcher_config: FetcherConfig | None = None

    def collect(self) -> ScrapeCollection:
        return asyncio.run(self._collect_async())

    async def _collect_async(self) -> ScrapeCollection:
        fetcher = AsyncHttpFetcher(self.fetcher_config)
        try:
            logger.info("Fetching route index: %s", self.source_url)
            index_html = await fetcher.get_text(self.source_url)
            route_urls = limited(parse_route_links(index_html, base_url=self.source_url), self.limit)
            logger.info("Discovered %s route links", len(route_urls))
            if not route_urls:
                raise RuntimeError(f"route catalogue empty at {self.source_url}")

            semaphore = asyncio.Semaphore(self.concurrency)
            results = await asyncio.gather(
                *[
                    self._fetch_one(fetcher, semaphore, index, len(route_urls), route_url)
                    for index, route_url in enumerate(route_urls, start=1)
                ]
            )
        finally:
            await fetcher.close()

        hard_failures: list[str] = []
        warnings: list[str] = []
        snapshots: list[RouteSnapshot] = []
        for _index, route_url, snapshot, error, route_warnings in sorted(results, key=lambda item: item[0]):
            if error is not None:
                hard_failures.append(route_url)
                logger.warning("Hard failure for still-listed route %s: %s", route_url, error)
                continue
            if snapshot is None:
                hard_failures.append(route_url)
                logger.warning(
                    "Hard failure for still-listed route %s: missing snapshot without error detail",
                    route_url,
                )
                continue
            snapshots.append(snapshot)
            warnings.extend(route_warnings)

        if hard_failures:
            return ScrapeCollection(
                rows=_EMPTY_ROWS,
                hard_failures=tuple(hard_failures),
                warnings=tuple(warnings),
            )

        return ScrapeCollection(
            rows=snapshots_to_canonical_rows(snapshots),
            hard_failures=(),
            warnings=tuple(warnings),
        )

    async def _fetch_one(
        self,
        fetcher: AsyncHttpFetcher,
        semaphore: asyncio.Semaphore,
        index: int,
        total: int,
        route_url: str,
    ) -> tuple[int, str, RouteSnapshot | None, str | None, tuple[str, ...]]:
        async with semaphore:
            try:
                logger.info("Fetching route %s/%s: %s", index, total, route_url)
                route_html = await fetcher.get_text(route_url)
                route = parse_route_page(route_html, page_url=route_url)
                soft_warnings: list[str] = []
                if not route.map_url:
                    soft_warnings.append(f"route {route.code}: map unavailable")
                map_text = await fetcher.get_text(route.map_url) if route.map_url else ""
                directions = parse_kml_directions(extract_kml(map_text)) if map_text else []
                direction_matches = infer_service_direction_matches(route.service_directions, directions)
                low_confidence = sum(
                    1
                    for match in direction_matches
                    if match.confidence in {DirectionMatchConfidence.LOW, DirectionMatchConfidence.NONE}
                )
                if low_confidence:
                    soft_warnings.append(f"route {route.code}: {low_confidence} low-confidence direction matches")
                snapshot = RouteSnapshot(
                    route=route,
                    directions=directions,
                    direction_matches=direction_matches,
                    source_hash=hash_text(route_html),
                    map_hash=hash_text(map_text) if map_text else None,
                )
                return index, route_url, snapshot, None, tuple(soft_warnings)
            except Exception as exc:
                return index, route_url, None, str(exc), ()
