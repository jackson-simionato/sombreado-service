"""Assemble a ParsedRoutePage from Consórcio HTML."""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from sombreado.ingestion.domain import ParsedRoutePage
from sombreado.ingestion.parsers.fares import parse_fare_policy
from sombreado.ingestion.parsers.html import first_labeled_value, text
from sombreado.ingestion.parsers.itinerary import parse_itinerary
from sombreado.ingestion.parsers.schedules import parse_schedules, parse_service_directions


def parse_route_page(html: str, page_url: str) -> ParsedRoutePage:
    soup = BeautifulSoup(html, "html.parser")
    code, name = parse_title(soup, page_url)
    slug, _ = route_identity_from_url(page_url)
    map_url = extract_map_url(soup, page_url)
    service_directions = parse_service_directions(soup)
    fare_region = first_labeled_value(soup, "Tarifa")

    return ParsedRoutePage(
        code=code,
        name=name,
        slug=slug,
        page_url=page_url,
        map_url=map_url,
        category=first_labeled_value(soup, "Característica", "Categoria"),
        fare_region=fare_region,
        fare_policy=parse_fare_policy(soup, fare_region),
        last_changed=parse_brazilian_date(first_labeled_value(soup, "Alterada em", "Última alteração")),
        service_directions=service_directions,
        schedules=parse_schedules(soup),
        itinerary_steps=parse_itinerary(soup),
    )


def parse_title(soup: BeautifulSoup, page_url: str) -> tuple[str, str]:
    slug, code = route_identity_from_url(page_url)
    title = text(soup.find("h1")) or text(soup.find("title"))
    if title:
        separator_match = re.match(rf"\s*{re.escape(code)}\s*[-\u2013]\s*(.+?)\s*$", title, re.IGNORECASE)
        if separator_match:
            name = re.sub(
                r"\s*\|\s*Linha\s*\|\s*Consórcio Fênix\s*$",
                "",
                separator_match.group(1),
                flags=re.IGNORECASE,
            )
            return code, name
    return code, slug.replace("-", " ").title()


def route_identity_from_url(page_url: str) -> tuple[str, str]:
    path_tail = unquote(urlparse(page_url).path.rstrip("/").split("/")[-1])
    if "," not in path_tail:
        raise ValueError("Could not parse route code and name")
    slug, code = (part.strip() for part in path_tail.rsplit(",", 1))
    if not slug or not code:
        raise ValueError("Could not parse route code and name")
    return slug, code


def extract_map_url(soup: BeautifulSoup, page_url: str) -> str | None:
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src")
        if src and ("/mapa/" in src or re.search(r"\.kml(?:$|\?)", src, re.IGNORECASE)):
            return urljoin(page_url, src)
    link = soup.find("a", href=re.compile(r"(/mapa/|\.kml(?:$|\?))", re.IGNORECASE))
    if isinstance(link, Tag) and link.get("href"):
        return urljoin(page_url, str(link["href"]))
    return None


def parse_brazilian_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", value)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    return date(year, month, day)
