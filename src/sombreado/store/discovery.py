"""Current-generation Route Discovery, Direction Choices, and Route Geometry reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from geoalchemy2 import Geography
from sqlalchemy import ColumnElement, and_, cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from sombreado.store.models import (
    DatasetPointerRecord,
    DatasetRouteVersionRecord,
    RouteDirectionRecord,
    RouteRecord,
    RouteSegmentRecord,
    ServiceDirectionRecord,
)

PUBLIC_DIRECTION_LABEL_CONFIDENCES = ("high", "medium")

AdviceRouteContextStatus = Literal["route_not_found", "route_version_stale", "route_direction_not_found", "ok"]


@dataclass(frozen=True)
class RouteCandidateRow:
    route_id: str
    route_version_id: str
    route_code: str
    route_name: str
    direction_hints: tuple[str, ...]
    distance_meters: float | None = None


@dataclass(frozen=True)
class DirectionChoiceRow:
    route_direction_id: str
    sequence: int
    name: str
    direction_kind: str | None
    departure_labels: tuple[str, ...]


@dataclass(frozen=True)
class RouteSegmentRow:
    public_id: str
    sequence: int
    geometry: str
    bearing_degrees: float
    distance_meters: float
    cumulative_distance_meters: float


@dataclass(frozen=True)
class AdviceRouteContextRow:
    """Single-session result for advice route/version/direction + segments (#99)."""

    status: AdviceRouteContextStatus
    segments: tuple[RouteSegmentRow, ...] = ()


def resolve_advice_route_context_status(
    *,
    current_route_version_id: str | None,
    requested_route_version_id: str,
    direction_belongs: bool,
) -> AdviceRouteContextStatus:
    """Map version/membership checks to a single advice-context status."""
    if current_route_version_id is None:
        return "route_not_found"
    if current_route_version_id != requested_route_version_id:
        return "route_version_stale"
    if not direction_belongs:
        return "route_direction_not_found"
    return "ok"


def _current_pointer_join() -> ColumnElement[bool]:
    """Join predicate: dataset membership is visible via the `current` pointer."""
    return and_(
        DatasetPointerRecord.generation_id == DatasetRouteVersionRecord.generation_id,
        DatasetPointerRecord.role == "current",
    )


def search_route_candidates_statement(*, query: str, limit: int) -> Select:
    """Build the ORM select for current-generation Route Candidate search."""
    pattern = f"%{query}%"
    return (
        select(
            RouteRecord.id.label("route_id"),
            DatasetRouteVersionRecord.route_version_id.label("route_version_id"),
            RouteRecord.code.label("route_code"),
            RouteRecord.name.label("route_name"),
        )
        .select_from(RouteRecord)
        .join(DatasetRouteVersionRecord, DatasetRouteVersionRecord.route_id == RouteRecord.id)
        .join(DatasetPointerRecord, _current_pointer_join())
        .where(or_(RouteRecord.code.ilike(pattern), RouteRecord.name.ilike(pattern)))
        .order_by(RouteRecord.code.asc(), RouteRecord.name.asc())
        .limit(limit)
    )


def nearby_route_candidates_statement(*, lat: float, lng: float, radius_meters: float, limit: int) -> Select:
    """Build the ORM select for current-generation nearby Route Candidates.

    Drive from ``route_segments`` via a materialized spatial CTE so Postgres uses
    ``route_segments_geom_gix`` once, then joins ``current`` membership (#96).
    The previous ``FROM dataset_route_versions`` shape probed GIST once per current
    route (~187 loops in production EXPLAIN).
    """
    user_point = cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), Geography)
    nearby_segments = (
        select(
            RouteSegmentRecord.route_version_id.label("route_version_id"),
            RouteSegmentRecord.geom.label("geom"),
        )
        .where(func.ST_DWithin(RouteSegmentRecord.geom, user_point, radius_meters))
        .cte("nearby_segments")
        .prefix_with("MATERIALIZED")
    )
    distance = func.min(func.ST_Distance(nearby_segments.c.geom, user_point)).label("distance_meters")
    return (
        select(
            RouteRecord.id.label("route_id"),
            DatasetRouteVersionRecord.route_version_id.label("route_version_id"),
            RouteRecord.code.label("route_code"),
            RouteRecord.name.label("route_name"),
            distance,
        )
        .select_from(nearby_segments)
        .join(
            DatasetRouteVersionRecord,
            DatasetRouteVersionRecord.route_version_id == nearby_segments.c.route_version_id,
        )
        .join(DatasetPointerRecord, _current_pointer_join())
        .join(RouteRecord, RouteRecord.id == DatasetRouteVersionRecord.route_id)
        .group_by(
            RouteRecord.id,
            DatasetRouteVersionRecord.route_version_id,
            RouteRecord.code,
            RouteRecord.name,
        )
        .order_by(distance.asc(), RouteRecord.code.asc(), RouteRecord.name.asc(), RouteRecord.id.asc())
        .limit(limit)
    )


def current_route_version_statement(*, route_id: str) -> Select:
    """Build the ORM select for the current-generation route version id."""
    return (
        select(DatasetRouteVersionRecord.route_version_id)
        .select_from(DatasetRouteVersionRecord)
        .join(DatasetPointerRecord, _current_pointer_join())
        .where(DatasetRouteVersionRecord.route_id == route_id)
    )


def direction_choices_statement(*, route_version_id: str) -> Select:
    """Build the ORM select for selectable Direction Choices on current."""
    return (
        select(
            RouteDirectionRecord.id.label("route_direction_id"),
            RouteDirectionRecord.sequence,
            RouteDirectionRecord.name,
            RouteDirectionRecord.direction_kind,
        )
        .select_from(RouteDirectionRecord)
        .join(
            DatasetRouteVersionRecord,
            DatasetRouteVersionRecord.route_version_id == RouteDirectionRecord.route_version_id,
        )
        .join(DatasetPointerRecord, _current_pointer_join())
        .where(RouteDirectionRecord.route_version_id == route_version_id)
        .order_by(RouteDirectionRecord.sequence.asc())
    )


def departure_labels_statement(*, route_version_id: str) -> Select:
    """Build the ORM select for public departure labels on current directions."""
    return (
        select(
            ServiceDirectionRecord.route_direction_id,
            ServiceDirectionRecord.departure_label,
        )
        .select_from(ServiceDirectionRecord)
        .join(RouteDirectionRecord, RouteDirectionRecord.id == ServiceDirectionRecord.route_direction_id)
        .join(
            DatasetRouteVersionRecord,
            DatasetRouteVersionRecord.route_version_id == RouteDirectionRecord.route_version_id,
        )
        .join(DatasetPointerRecord, _current_pointer_join())
        .where(
            ServiceDirectionRecord.route_direction_id.is_not(None),
            ServiceDirectionRecord.confidence.in_(PUBLIC_DIRECTION_LABEL_CONFIDENCES),
            RouteDirectionRecord.route_version_id == route_version_id,
        )
        .order_by(RouteDirectionRecord.sequence.asc(), ServiceDirectionRecord.sequence.asc())
    )


def direction_hints_statement(*, version_ids: list[str]) -> Select:
    """Build the ORM select for Route Candidate direction hints on current."""
    return (
        select(
            RouteDirectionRecord.route_version_id,
            ServiceDirectionRecord.departure_label,
        )
        .select_from(ServiceDirectionRecord)
        .join(RouteDirectionRecord, RouteDirectionRecord.id == ServiceDirectionRecord.route_direction_id)
        .join(
            DatasetRouteVersionRecord,
            DatasetRouteVersionRecord.route_version_id == RouteDirectionRecord.route_version_id,
        )
        .join(DatasetPointerRecord, _current_pointer_join())
        .where(
            ServiceDirectionRecord.route_direction_id.is_not(None),
            ServiceDirectionRecord.confidence.in_(PUBLIC_DIRECTION_LABEL_CONFIDENCES),
            RouteDirectionRecord.route_version_id.in_(version_ids),
        )
        .order_by(
            RouteDirectionRecord.route_version_id.asc(),
            RouteDirectionRecord.sequence.asc(),
            ServiceDirectionRecord.sequence.asc(),
        )
    )


def route_direction_membership_statement(*, route_version_id: str, route_direction_id: str) -> Select:
    """Build the ORM select for current-generation direction membership."""
    return (
        select(RouteDirectionRecord.id)
        .select_from(RouteDirectionRecord)
        .join(
            DatasetRouteVersionRecord,
            DatasetRouteVersionRecord.route_version_id == RouteDirectionRecord.route_version_id,
        )
        .join(DatasetPointerRecord, _current_pointer_join())
        .where(
            RouteDirectionRecord.route_version_id == route_version_id,
            RouteDirectionRecord.id == route_direction_id,
        )
    )


def current_route_segments_statement(*, route_version_id: str, route_direction_id: str) -> Select:
    """Build the ORM select for ordered current-generation route segments."""
    return (
        select(
            RouteSegmentRecord.public_id,
            RouteSegmentRecord.sequence,
            RouteSegmentRecord.geometry,
            RouteSegmentRecord.bearing_degrees,
            RouteSegmentRecord.distance_meters,
            RouteSegmentRecord.cumulative_distance_meters,
        )
        .select_from(RouteSegmentRecord)
        .join(
            DatasetRouteVersionRecord,
            DatasetRouteVersionRecord.route_version_id == RouteSegmentRecord.route_version_id,
        )
        .join(DatasetPointerRecord, _current_pointer_join())
        .where(
            RouteSegmentRecord.route_version_id == route_version_id,
            RouteSegmentRecord.route_direction_id == route_direction_id,
        )
        .order_by(RouteSegmentRecord.sequence.asc())
    )


def search_route_candidates(
    session: Session,
    *,
    query: str,
    limit: int,
) -> tuple[RouteCandidateRow, ...]:
    """Return current-generation Route Candidates matching code or name."""
    rows = session.execute(search_route_candidates_statement(query=query, limit=limit)).mappings().all()
    version_ids = [str(row["route_version_id"]) for row in rows]
    hints_by_version = _direction_hints_by_version(session, version_ids)
    return tuple(
        RouteCandidateRow(
            route_id=str(row["route_id"]),
            route_version_id=str(row["route_version_id"]),
            route_code=str(row["route_code"]),
            route_name=str(row["route_name"]),
            direction_hints=hints_by_version.get(str(row["route_version_id"]), ()),
        )
        for row in rows
    )


def find_nearby_route_candidates(
    session: Session,
    *,
    lat: float,
    lng: float,
    radius_meters: float,
    limit: int,
) -> tuple[RouteCandidateRow, ...]:
    """Return current-generation nearby Route Candidates with PostGIS geography distance."""
    rows = (
        session.execute(
            nearby_route_candidates_statement(
                lat=lat,
                lng=lng,
                radius_meters=radius_meters,
                limit=limit,
            )
        )
        .mappings()
        .all()
    )
    version_ids = [str(row["route_version_id"]) for row in rows]
    hints_by_version = _direction_hints_by_version(session, version_ids)
    return tuple(
        RouteCandidateRow(
            route_id=str(row["route_id"]),
            route_version_id=str(row["route_version_id"]),
            route_code=str(row["route_code"]),
            route_name=str(row["route_name"]),
            direction_hints=hints_by_version.get(str(row["route_version_id"]), ()),
            distance_meters=float(row["distance_meters"]),
        )
        for row in rows
    )


def load_current_route_version_id(session: Session, route_id: str) -> str | None:
    """Return the current-generation route version id for a route, if any."""
    row = session.execute(current_route_version_statement(route_id=route_id)).first()
    return None if row is None else str(row[0])


def load_direction_choices(
    session: Session,
    *,
    route_version_id: str,
) -> tuple[DirectionChoiceRow, ...]:
    """Return selectable Direction Choices for a current-generation route version."""
    directions = session.execute(direction_choices_statement(route_version_id=route_version_id)).all()
    labels_by_direction: dict[str, list[str]] = {}
    for direction_id, label in session.execute(departure_labels_statement(route_version_id=route_version_id)):
        bucket = labels_by_direction.setdefault(str(direction_id), [])
        text_label = str(label)
        if text_label not in bucket:
            bucket.append(text_label)

    rows = [
        DirectionChoiceRow(
            route_direction_id=str(row.route_direction_id),
            sequence=int(row.sequence),
            name=str(row.name),
            direction_kind=None if row.direction_kind is None else str(row.direction_kind),
            departure_labels=tuple(labels_by_direction.get(str(row.route_direction_id), [])),
        )
        for row in directions
    ]
    kind_order = {"ida": 0, "volta": 1, None: 2}
    rows.sort(key=lambda direction: (kind_order.get(direction.direction_kind, 2), direction.sequence))
    return tuple(rows)


def route_direction_belongs_to_version(
    session: Session,
    *,
    route_version_id: str,
    route_direction_id: str,
) -> bool:
    """Return whether the direction belongs to the current-generation route version."""
    row = session.execute(
        route_direction_membership_statement(
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
        )
    ).first()
    return row is not None


def load_current_route_segments(
    session: Session,
    *,
    route_version_id: str,
    route_direction_id: str,
) -> tuple[RouteSegmentRow, ...]:
    """Return ordered current-generation route segments for one direction choice."""
    rows = session.execute(
        current_route_segments_statement(
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
        )
    ).all()
    return tuple(
        RouteSegmentRow(
            public_id=str(row.public_id),
            sequence=int(row.sequence),
            geometry=str(row.geometry),
            bearing_degrees=float(row.bearing_degrees),
            distance_meters=float(row.distance_meters),
            cumulative_distance_meters=float(row.cumulative_distance_meters),
        )
        for row in rows
    )


def load_advice_route_context(
    session: Session,
    *,
    route_id: str,
    route_version_id: str,
    route_direction_id: str,
) -> AdviceRouteContextRow:
    """Load advice prerequisites in one session: current version, membership, segments."""
    current_route_version_id = load_current_route_version_id(session, route_id)
    direction_belongs = False
    if current_route_version_id == route_version_id:
        direction_belongs = route_direction_belongs_to_version(
            session,
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
        )
    status = resolve_advice_route_context_status(
        current_route_version_id=current_route_version_id,
        requested_route_version_id=route_version_id,
        direction_belongs=direction_belongs,
    )
    if status != "ok":
        return AdviceRouteContextRow(status=status)
    return AdviceRouteContextRow(
        status="ok",
        segments=load_current_route_segments(
            session,
            route_version_id=route_version_id,
            route_direction_id=route_direction_id,
        ),
    )


def _direction_hints_by_version(
    session: Session,
    version_ids: list[str],
) -> dict[str, tuple[str, ...]]:
    if not version_ids:
        return {}
    hints: dict[str, list[str]] = {version_id: [] for version_id in version_ids}
    for version_id, label in session.execute(direction_hints_statement(version_ids=version_ids)):
        bucket = hints.setdefault(str(version_id), [])
        text_label = str(label)
        if text_label not in bucket:
            bucket.append(text_label)
    return {version_id: tuple(labels) for version_id, labels in hints.items()}
