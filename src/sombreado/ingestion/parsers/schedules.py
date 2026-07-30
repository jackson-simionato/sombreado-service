"""Schedule and service-direction extraction from Consórcio route pages."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from sombreado.ingestion.domain import ScheduleEntry, ServiceDirection
from sombreado.ingestion.parsers.html import text

TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")
FLAG_RE = re.compile(r"(?<!\w)([E*MR])(?!\w)")


def parse_schedules(soup: BeautifulSoup) -> list[ScheduleEntry]:
    schedules: list[ScheduleEntry] = []
    schedules.extend(parse_schedule_cards(soup))
    root = soup.find(id=re.compile("horario", re.IGNORECASE)) or soup
    for table in root.find_all("table"):
        day_type = table_day_type(table)
        if not day_type:
            continue
        headers = [text(cell) for cell in table.find_all("th")]
        if not headers:
            continue
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            for index, cell in enumerate(cells):
                label = headers[index] if index < len(headers) else headers[-1]
                schedules.extend(parse_schedule_cell(day_type, label, text(cell)))
    return schedules


def parse_service_directions(soup: BeautifulSoup) -> list[ServiceDirection]:
    directions_by_label: dict[str, ServiceDirection] = {}
    for sequence, tab in enumerate(soup.find_all(class_=re.compile(r"\bmy-subtab-content\b")), start=1):
        if not isinstance(tab, Tag):
            continue
        heading = tab.find(re.compile("^h[1-6]$"))
        label = text(heading)
        if not label:
            continue
        schedules = parse_schedule_cards_in_group(tab, label)
        if not schedules:
            continue
        direction = directions_by_label.get(label)
        if direction is None:
            directions_by_label[label] = ServiceDirection(
                sequence=sequence,
                departure_label=label,
                schedules=schedules,
            )
            continue
        existing_keys = {schedule_key(existing) for existing in direction.schedules}
        direction.schedules.extend(entry for entry in schedules if schedule_key(entry) not in existing_keys)
    if directions_by_label:
        return sorted(directions_by_label.values(), key=lambda direction: direction.sequence)
    return parse_table_service_directions(soup)


def parse_table_service_directions(soup: BeautifulSoup) -> list[ServiceDirection]:
    grouped: dict[str, list[ScheduleEntry]] = {}
    order: list[str] = []
    root = soup.find(id=re.compile("horario", re.IGNORECASE)) or soup
    for table in root.find_all("table"):
        day_type = table_day_type(table)
        if not day_type:
            continue
        headers = [text(cell) for cell in table.find_all("th")]
        if not headers:
            continue
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            for index, cell in enumerate(cells):
                label = headers[index] if index < len(headers) else headers[-1]
                if label not in grouped:
                    grouped[label] = []
                    order.append(label)
                entries = parse_schedule_cell(day_type, label, text(cell))
                for entry in entries:
                    if schedule_key(entry) not in {schedule_key(existing) for existing in grouped[label]}:
                        grouped[label].append(entry)
    return [
        ServiceDirection(sequence=index, departure_label=label, schedules=grouped[label])
        for index, label in enumerate(order, start=1)
        if grouped[label]
    ]


def parse_schedule_cards(soup: BeautifulSoup) -> list[ScheduleEntry]:
    schedules: list[ScheduleEntry] = []
    seen: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for node in soup.find_all(attrs={"data-semana": True, "data-horario": True}):
        if not isinstance(node, Tag):
            continue
        day_type = str(node["data-semana"]).strip()
        time = str(node["data-horario"]).strip()
        if not day_type or not TIME_RE.fullmatch(time):
            continue
        label = schedule_card_label(node)
        entry = ScheduleEntry(
            day_type=day_type,
            departure_label=label,
            time=time.zfill(5),
            flags=tuple(FLAG_RE.findall(text(node))),
        )
        key = schedule_key(entry)
        if key not in seen:
            seen.add(key)
            schedules.append(entry)
    return schedules


def parse_schedule_cards_in_group(group: Tag, label: str) -> list[ScheduleEntry]:
    schedules: list[ScheduleEntry] = []
    seen: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for node in group.find_all(attrs={"data-semana": True, "data-horario": True}):
        if not isinstance(node, Tag):
            continue
        day_type = str(node["data-semana"]).strip()
        time = str(node["data-horario"]).strip()
        if not day_type or not TIME_RE.fullmatch(time):
            continue
        entry = ScheduleEntry(
            day_type=day_type,
            departure_label=label,
            time=time.zfill(5),
            flags=tuple(FLAG_RE.findall(text(node))),
        )
        key = schedule_key(entry)
        if key not in seen:
            seen.add(key)
            schedules.append(entry)
    return schedules


def schedule_key(entry: ScheduleEntry) -> tuple[str, str, str, tuple[str, ...]]:
    return entry.day_type, entry.departure_label, entry.time, entry.flags


def schedule_card_label(node: Tag) -> str:
    tab = node.find_parent(class_=re.compile(r"\bmy-subtab-content\b"))
    if isinstance(tab, Tag):
        heading = tab.find(re.compile("^h[1-6]$"))
        label = text(heading)
        if label:
            return label
    return ""


def table_day_type(table: Tag) -> str:
    caption = table.find("caption")
    caption_text = text(caption)
    if caption_text:
        return caption_text
    heading = table.find_previous(re.compile("^h[1-6]$"))
    return text(heading)


def parse_schedule_cell(day_type: str, label: str, value: str) -> list[ScheduleEntry]:
    entries: list[ScheduleEntry] = []
    for time_match in TIME_RE.finditer(value):
        token_end = next_time_start(value, time_match.end())
        token = value[time_match.start() : token_end]
        entries.append(
            ScheduleEntry(
                day_type=day_type,
                departure_label=label,
                time=time_match.group(1).zfill(5),
                flags=tuple(FLAG_RE.findall(token)),
            )
        )
    return entries


def next_time_start(value: str, start: int) -> int:
    match = TIME_RE.search(value, start)
    return match.start() if match else len(value)
