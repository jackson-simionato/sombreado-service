"""Passenger Route Discovery and Direction Choices from the Generation Store current pointer."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from sombreado.domain.schemas import DirectionChoice, RouteCandidate, RouteDirectionKind
from sombreado.store.discovery import (
    RouteCandidateRow,
    find_nearby_route_candidates,
    load_current_route_version_id,
    load_direction_choices,
    search_route_candidates,
)
from sombreado.store.generation import GenerationStore

_T = TypeVar("_T")


class CurrentRouteReadService:
    """Read Route Candidates and Direction Choices from SQLite `current` only.

    Sync SQLite work runs in a worker thread via ``asyncio.to_thread`` so the
    FastAPI event loop is not blocked by connection open / query / close.
    """

    def __init__(self, store: GenerationStore) -> None:
        self._store = store

    async def search_route_candidates(self, *, query: str, limit: int) -> list[RouteCandidate]:
        rows = await self._run_sqlite(lambda connection: search_route_candidates(connection, query=query, limit=limit))
        return [_to_route_candidate(row) for row in rows]

    async def find_nearby_route_candidates(
        self,
        *,
        lat: float,
        lng: float,
        radius_meters: float,
        limit: int,
    ) -> list[RouteCandidate]:
        rows = await self._run_sqlite(
            lambda connection: find_nearby_route_candidates(
                connection,
                lat=lat,
                lng=lng,
                radius_meters=radius_meters,
                limit=limit,
            )
        )
        return [_to_route_candidate(row) for row in rows]

    async def load_current_route_version_id(self, route_id: UUID) -> UUID | None:
        version_id = await self._run_sqlite(lambda connection: load_current_route_version_id(connection, str(route_id)))
        return None if version_id is None else UUID(version_id)

    async def load_direction_choices(self, *, route_version_id: UUID) -> list[DirectionChoice]:
        rows = await self._run_sqlite(
            lambda connection: load_direction_choices(connection, route_version_id=str(route_version_id))
        )
        return [
            DirectionChoice(
                route_direction_id=UUID(row.route_direction_id),
                sequence=row.sequence,
                name=row.name,
                direction_kind=_to_direction_kind(row.direction_kind),
                departure_labels=list(row.departure_labels),
            )
            for row in rows
        ]

    async def _run_sqlite(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        def run() -> _T:
            with self._store.connection() as connection:
                return operation(connection)

        return await asyncio.to_thread(run)


def _to_route_candidate(row: RouteCandidateRow) -> RouteCandidate:
    return RouteCandidate(
        route_id=UUID(row.route_id),
        route_version_id=UUID(row.route_version_id),
        route_code=row.route_code,
        route_name=row.route_name,
        direction_hints=list(row.direction_hints),
        distance_meters=row.distance_meters,
    )


def _to_direction_kind(value: str | None) -> RouteDirectionKind | None:
    if value is None:
        return None
    return RouteDirectionKind(value)
