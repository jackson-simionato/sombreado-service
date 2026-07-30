"""Itinerary step extraction from Consórcio route pages."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from sombreado.ingestion.domain import ItineraryStep
from sombreado.ingestion.parsers.html import text


def parse_itinerary(soup: BeautifulSoup) -> list[ItineraryStep]:
    root = soup.find(class_=re.compile(r"\bcontent-text-itinerario\b")) or soup.find(
        id=re.compile("itiner", re.IGNORECASE)
    )
    if not isinstance(root, Tag):
        heading = soup.find(string=re.compile("Itiner", re.IGNORECASE))
        root = heading.find_parent().find_next_sibling() if heading and heading.find_parent() else None
    if not isinstance(root, Tag):
        return []

    items = root.find_all("li")
    if not items:
        items = root.find_all(["p", "span"])
    return [ItineraryStep(sequence=index, name=text(item)) for index, item in enumerate(items, start=1) if text(item)]
