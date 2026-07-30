"""Fare policy extraction from Consórcio route pages."""

from __future__ import annotations

import re
from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from sombreado.ingestion.domain import FarePolicy
from sombreado.ingestion.parsers.html import first_labeled_value, text


def parse_fare_policy(soup: BeautifulSoup, region: str | None) -> FarePolicy | None:
    if not region:
        return None
    citizen_card_cents = parse_fare(first_labeled_value(soup, "Cartão Cidadão", "Cartao Cidadao"))
    vt_tourist_card_cents = parse_fare(first_labeled_value(soup, "Cartão VT/Turista", "Cartao VT/Turista"))
    cash_qrcode_pix_cents = parse_fare(
        first_labeled_value(
            soup,
            "Dinheiro/QRCODE/PIX",
            "Dinheiro/QRCODE",
            "Dinheiro/QRCode/PIX",
            "Dinheiro/QRCode",
        )
    )
    if citizen_card_cents is None or vt_tourist_card_cents is None or cash_qrcode_pix_cents is None:
        banner_fares = parse_conventional_fare_banner(soup)
        if citizen_card_cents is None:
            citizen_card_cents = banner_fares.get("citizen_card_cents")
        if vt_tourist_card_cents is None:
            vt_tourist_card_cents = banner_fares.get("vt_tourist_card_cents")
        if cash_qrcode_pix_cents is None:
            cash_qrcode_pix_cents = banner_fares.get("cash_qrcode_pix_cents")
    if citizen_card_cents is None and vt_tourist_card_cents is None and cash_qrcode_pix_cents is None:
        return None
    return FarePolicy(
        region=region,
        citizen_card_cents=citizen_card_cents,
        vt_tourist_card_cents=vt_tourist_card_cents,
        cash_qrcode_pix_cents=cash_qrcode_pix_cents,
    )


def parse_conventional_fare_banner(soup: BeautifulSoup) -> dict[str, int]:
    fares: dict[str, int] = {}
    banner = fare_banner_text(soup)
    if not banner:
        return fares
    conventional_text = re.split(r"\|\s*Tarifa\s+Executivo\b", banner, maxsplit=1, flags=re.IGNORECASE)[0]
    cash_match = re.search(
        r"Dinheiro\s*/\s*QRCODE\s*/\s*PIX\s*R\$\s*(\d+(?:[,.]\d{2})?)",
        conventional_text,
        re.IGNORECASE,
    )
    citizen_match = re.search(r"\bCidad[aã]o\s*R\$\s*(\d+(?:[,.]\d{2})?)", conventional_text, re.IGNORECASE)
    vt_tourist_match = re.search(r"\bVT\.?\s*e\s*Turista\s*R\$\s*(\d+(?:[,.]\d{2})?)", conventional_text, re.IGNORECASE)
    if cash_match:
        fares["cash_qrcode_pix_cents"] = parse_fare(cash_match.group(1)) or 0
    if citizen_match:
        fares["citizen_card_cents"] = parse_fare(citizen_match.group(1)) or 0
    if vt_tourist_match:
        fares["vt_tourist_card_cents"] = parse_fare(vt_tourist_match.group(1)) or 0
    return fares


def fare_banner_text(soup: BeautifulSoup) -> str | None:
    banner = soup.find(id="tarifas")
    if isinstance(banner, Tag):
        return text(banner)
    for candidate in soup.stripped_strings:
        if re.search(r"Tarifa\s+Convencional", candidate, re.IGNORECASE):
            return candidate.strip()
    return None


def parse_fare(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:[,.]\d{2})?)", value)
    if not match:
        return None
    decimal = Decimal(match.group(1).replace(",", "."))
    return int(decimal * 100)
