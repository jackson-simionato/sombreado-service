from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from urllib import robotparser
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.consorciofenix.com.br"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetcherConfig:
    user_agent: str = "sombreado-service/0.1 (+https://github.com/jackson-simionato/sombreado-service)"
    timeout_seconds: float = 20.0
    retries: int = 2
    rate_limit_seconds: float = 0.5


class AsyncHttpFetcher:
    def __init__(self, config: FetcherConfig | None = None) -> None:
        self.config = config or FetcherConfig()
        self.client = httpx.AsyncClient(
            headers={"User-Agent": self.config.user_agent},
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
        )
        self._robots: robotparser.RobotFileParser | None = None
        self._robots_lock = asyncio.Lock()

    async def get_text(self, url: str) -> str:
        await self.assert_allowed(url)
        return (await self._get_response(url)).text

    async def assert_allowed(self, url: str) -> None:
        robots = await self._load_robots(url)
        logger.debug("Checking robots.txt permission for %s", url)
        if not robots.can_fetch(self.config.user_agent, url):
            logger.error("robots.txt disallows fetching %s", url)
            raise PermissionError(f"robots.txt disallows fetching {url}")

    async def _load_robots(self, url: str) -> robotparser.RobotFileParser:
        if self._robots is not None:
            return self._robots
        async with self._robots_lock:
            if self._robots is not None:
                return self._robots
            robots_url = urljoin(url, "/robots.txt")
            logger.info("Fetching robots.txt: %s", robots_url)
            response = await self._get_response(robots_url)
            parser = robotparser.RobotFileParser()
            parser.parse(response.text.splitlines())
            self._robots = parser
            return parser

    async def _get_response(self, url: str) -> httpx.Response:
        last_error: Exception | None = None
        attempts = self.config.retries + 1
        for attempt in range(attempts):
            try:
                if attempt:
                    logger.info("Retrying fetch attempt %s/%s: %s", attempt + 1, attempts, url)
                    await asyncio.sleep(self.config.rate_limit_seconds)
                logger.debug("Fetching URL: %s", url)
                response = await self.client.get(url)
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("Fetch attempt %s/%s failed for %s: %s", attempt + 1, attempts, url, exc)
        logger.error("Failed to fetch %s after %s attempts", url, attempts)
        raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error

    async def close(self) -> None:
        await self.client.aclose()


def parse_route_links(index_html: str, base_url: str = BASE_URL) -> list[str]:
    soup = BeautifulSoup(index_html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if "/horarios/" not in href or "," not in href:
            continue
        url = urljoin(base_url, href)
        if url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def limited(items: Iterable[str], limit: int | None) -> list[str]:
    values = list(items)
    return values[:limit] if limit is not None else values
