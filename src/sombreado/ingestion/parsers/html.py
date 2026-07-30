"""Shared BeautifulSoup text helpers for Consórcio HTML parsers."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag


def text(node: Tag | object | None) -> str:
    if not isinstance(node, Tag):
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def find_labeled_value(soup: BeautifulSoup, label: str) -> str | None:
    pattern = re.compile(rf"{re.escape(label)}\s*(?::|-)\s*(.+)", re.IGNORECASE)
    for candidate in soup.stripped_strings:
        match = pattern.search(candidate)
        if match:
            return match.group(1).strip()
    for node in soup.find_all(string=re.compile(rf"^\s*{re.escape(label)}\s*:?\s*$", re.IGNORECASE)):
        parent = node.parent
        if not isinstance(parent, Tag):
            continue
        sibling = parent.find_next_sibling()
        while isinstance(sibling, Tag):
            value = text(sibling)
            if value:
                return value
            sibling = sibling.find_next_sibling()
    return None


def first_labeled_value(soup: BeautifulSoup, *labels: str) -> str | None:
    for label in labels:
        value = find_labeled_value(soup, label)
        if value:
            return value
    return None
