"""Passenger Route Discovery, Direction Choices, Geometry, and Advice reads from current."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

from sqlalchemy.orm import Session

from sombreado.domain.geometry import parse_linestring_wkt
from sombreado.domain.schemas import DirectionChoice, RouteCandidate, RouteDirectionKind, RouteSegment
from sombreado.logging import get_logger
from sombreado.store.discovery import (
    AdviceRouteContextStatus,
    RouteCandidateRow,
    RouteSegmentRow,
    find_nearby_route_candidates,
    load_advice_route_context,
    load_current_route_segments,
    load_current_route_version_id,
    load_direction_choices,
    route_direction_belongs_to_version,
    search_route_candidates,
)
from sombreado.store.generation import GenerationStore

_T = TypeVar("_T")

logger = get_logger(__name__)


@dataclass(frozen=True)
class AdviceRouteContext:
    status: AdviceRouteContextStatus
    segments: list[RouteSegment]


class CurrentRouteReadService:
    """Read passenger route data from Generation Store `current` only.

    Sync ORM / Postgres work runs in a worker thread via ``asyncio.to_thread`` so the
    FastAPI event loop is not blocked by connection open / query / close.
    """

    def __init__(self, store: GenerationStore) -> None:
        self._store = store

    async def search_route_candidates(self, *, query: str, limit: int) -> list[RouteCandidate]:
        rows = await self._run_session(
            "search_route_candidates",
            lambda session: search_route_candidates(session, query=query, limit=limit),
        )
        return [_to_route_candidate(row) for row in rows]

    async def find_nearby_route_candidates(
        self,
        *,
        lat: float,
        lng: float,
        radius_meters: float,
        limit: int,
    ) -> list[RouteCandidate]:
        rows = await self._run_session(
            "find_nearby_route_candidates",
            lambda session: find_nearby_route_candidates(
                session,
                lat=lat,
                lng=lng,
                radius_meters=radius_meters,
                limit=limit,
            ),
        )
        return [_to_route_candidate(row) for row in rows]

    async def load_current_route_version_id(self, route_id: UUID) -> UUID | None:
        version_id = await self._run_session(
            "load_current_route_version_id",
            lambda session: load_current_route_version_id(session, str(route_id)),
        )
        return None if version_id is None else UUID(version_id)

    async def load_direction_choices(self, *, route_version_id: UUID) -> list[DirectionChoice]:
        rows = await self._run_session(
            "load_direction_choices",
            lambda session: load_direction_choices(session, route_version_id=str(route_version_id)),
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

    async def route_direction_belongs_to_version(
        self,
        *,
        route_version_id: UUID,
        route_direction_id: UUID,
    ) -> bool:
        return await self._run_session(
            "route_direction_belongs_to_version",
            lambda session: route_direction_belongs_to_version(
                session,
                route_version_id=str(route_version_id),
                route_direction_id=str(route_direction_id),
            ),
        )

    async def load_current_route_segments(
        self,
        *,
        route_version_id: UUID,
        route_direction_id: UUID,
    ) -> list[RouteSegment]:
        rows = await self._run_session(
            "load_current_route_segments",
            lambda session: load_current_route_segments(
                session,
                route_version_id=str(route_version_id),
                route_direction_id=str(route_direction_id),
            ),
        )
        return [_to_route_segment(row) for row in rows]

    async def load_advice_route_context(
        self,
        *,
        route_id: UUID,
        route_version_id: UUID,
        route_direction_id: UUID,
    ) -> AdviceRouteContext:
        """Validate current version + direction and load segments in one DB session (#99)."""
        row = await self._run_session(
            "load_advice_route_context",
            lambda session: load_advice_route_context(
                session,
                route_id=str(route_id),
                route_version_id=str(route_version_id),
                route_direction_id=str(route_direction_id),
            ),
        )
        return AdviceRouteContext(
            status=row.status,
            segments=[_to_route_segment(segment) for segment in row.segments],
        )

    async def _run_session(self, operation_name: str, operation: Callable[[Session], _T]) -> _T:
        def run() -> _T:
            with self._store.session() as session:
                started = time.perf_counter()
                # Force checkout so connect/TLS/pre-ping is not folded into query_ms.
                session.connection()
                connect_ms = round((time.perf_counter() - started) * 1000)
                started = time.perf_counter()
                result = operation(session)
                query_ms = round((time.perf_counter() - started) * 1000)
            logger.info(
                "db_session operation=%s connect_ms=%s query_ms=%s",
                operation_name,
                connect_ms,
                query_ms,
            )
            return result

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


def _to_route_segment(row: RouteSegmentRow) -> RouteSegment:
    return RouteSegment(
        id=UUID(row.public_id),
        sequence=row.sequence,
        coordinates=parse_linestring_wkt(row.geometry),
        bearing_degrees=row.bearing_degrees,
        distance_meters=row.distance_meters,
        cumulative_distance_meters=row.cumulative_distance_meters,
    )


def _to_direction_kind(value: str | None) -> RouteDirectionKind | None:
    if value is None:
        return None
    return RouteDirectionKind(value)
