from uuid import UUID

from geoalchemy2 import Geography
from sqlalchemy import Float, Text, and_, bindparam, cast, func, literal, or_, select, true
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by, array
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models import (
    RouteDirectionRecord,
    RouteRecord,
    RouteSegmentRecord,
    RouteVersionRecord,
    ServiceDirectionRecord,
)
from app.schemas import (
    CandidateRouteDirection,
    DirectionChoice,
    LatLngPoint,
    LightweightRouteDirection,
    RouteCandidate,
    RouteSegment,
    RouteSummary,
)
from app.services.geometry import parse_linestring_wkt

logger = get_logger(__name__)
PUBLIC_DIRECTION_LABEL_CONFIDENCES = ("high", "medium")


class RouteReadService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_nearby_route_directions(
        self,
        *,
        lat: float,
        lng: float,
        radius_meters: float,
        limit: int,
    ) -> list[CandidateRouteDirection]:
        logger.info(
            "Finding nearby route directions lat=%s lng=%s radius_meters=%s limit=%s",
            lat,
            lng,
            radius_meters,
            limit,
        )
        rows = await self._session.execute(
            _nearby_route_directions_statement(),
            {"lat": lat, "lng": lng, "radius_meters": radius_meters, "limit": limit},
        )
        return [CandidateRouteDirection.model_validate(row._mapping) for row in rows]

    async def search_route_candidates(self, *, query: str, limit: int) -> list[RouteCandidate]:
        logger.info("Searching route candidates query=%s limit=%s", query, limit)
        rows = await self._session.execute(
            _search_route_candidates_statement(),
            {"query_pattern": f"%{query}%", "limit": limit},
        )
        return _route_candidates_from_rows(rows)

    async def find_nearby_route_candidates(
        self,
        *,
        lat: float,
        lng: float,
        radius_meters: float,
        limit: int,
    ) -> list[RouteCandidate]:
        logger.info(
            "Finding nearby route candidates lat=%s lng=%s radius_meters=%s limit=%s",
            lat,
            lng,
            radius_meters,
            limit,
        )
        rows = await self._session.execute(
            _nearby_route_candidates_statement(),
            {"lat": lat, "lng": lng, "radius_meters": radius_meters, "limit": limit},
        )
        return _route_candidates_from_rows(rows)

    async def list_current_routes(
        self,
        *,
        query: str | None,
        lat: float | None,
        lng: float | None,
        radius_meters: float | None,
        limit: int,
    ) -> list[RouteSummary]:
        location_values = (lat, lng, radius_meters)
        has_location = all(value is not None for value in location_values)
        if any(value is not None for value in location_values) and not has_location:
            raise ValueError("lat, lng, and radius_meters must be provided together")

        rows = await self._session.execute(
            _list_current_routes_statement(has_location=has_location),
            {
                "query_pattern": f"%{query}%" if query else None,
                "lat": lat,
                "lng": lng,
                "radius_meters": radius_meters,
                "limit": limit,
            },
        )
        return _route_summaries_from_rows(rows)

    async def load_current_route(self, route_id: UUID) -> RouteSummary | None:
        routes = await self._load_current_routes_by_id(route_id=route_id)
        return routes[0] if routes else None

    async def load_current_route_version_id(self, route_id: UUID) -> UUID | None:
        rows = await self._session.execute(_current_route_version_statement(), {"route_id": route_id})
        row = rows.first()
        return row.route_version_id if row else None

    async def load_direction_choices(self, *, route_version_id: UUID) -> list[DirectionChoice]:
        rows = await self._session.execute(_direction_choices_statement(), {"route_version_id": route_version_id})
        return [
            DirectionChoice(
                route_direction_id=values["route_direction_id"],
                sequence=values["sequence"],
                name=values["name"],
                departure_labels=_dedupe_preserving_order(values["departure_labels"] or []),
            )
            for values in (row._mapping for row in rows)
        ]

    async def route_direction_belongs_to_version(
        self,
        *,
        route_version_id: UUID,
        route_direction_id: UUID,
    ) -> bool:
        rows = await self._session.execute(
            _route_direction_membership_statement(),
            {"route_version_id": route_version_id, "route_direction_id": route_direction_id},
        )
        return rows.first() is not None

    async def load_current_route_directions(self, route_id: UUID) -> list[LightweightRouteDirection]:
        route = await self.load_current_route(route_id)
        return route.directions if route else []

    async def _load_current_routes_by_id(self, *, route_id: UUID) -> list[RouteSummary]:
        rows = await self._session.execute(_load_current_route_statement(), {"route_id": route_id})
        return _route_summaries_from_rows(rows)

    async def load_current_route_segments(
        self,
        *,
        route_version_id: UUID,
        route_direction_id: UUID,
    ) -> list[RouteSegment]:
        rows = await self._session.execute(
            _load_current_route_segments_statement(),
            {"route_version_id": route_version_id, "route_direction_id": route_direction_id},
        )
        return [
            RouteSegment(
                id=row.id,
                sequence=row.sequence,
                coordinates=parse_linestring_wkt(row.geometry_wkt),
                bearing_degrees=row.bearing_degrees,
                distance_meters=row.distance_meters,
                cumulative_distance_meters=row.cumulative_distance_meters,
            )
            for row in rows
        ]


def _geography(geometry):
    return cast(geometry, Geography)


def _public_service_direction_join_condition():
    return and_(
        ServiceDirectionRecord.route_direction_id == RouteDirectionRecord.id,
        ServiceDirectionRecord.route_direction_id.is_not(None),
        ServiceDirectionRecord.confidence.in_(PUBLIC_DIRECTION_LABEL_CONFIDENCES),
    )


def _user_point_cte():
    return select(
        cast(func.ST_SetSRID(func.ST_MakePoint(bindparam("lng"), bindparam("lat")), 4326), Geography).label("geog")
    ).cte("user_point")


def _departure_labels_expression():
    labels = func.array_remove(
        func.array_agg(
            aggregate_order_by(
                ServiceDirectionRecord.departure_label,
                ServiceDirectionRecord.sequence.asc(),
            )
        ),
        None,
    )
    return func.coalesce(labels, cast(array([], type_=Text()), ARRAY(Text()))).label("departure_labels")


def _direction_labels_cte(name: str = "direction_labels"):
    return (
        select(
            RouteDirectionRecord.id.label("route_direction_id"),
            _departure_labels_expression(),
        )
        .select_from(RouteDirectionRecord)
        .outerjoin(ServiceDirectionRecord, _public_service_direction_join_condition())
        .group_by(RouteDirectionRecord.id)
        .cte(name)
    )


def _route_candidate_hints_expression():
    labels = func.array_remove(
        func.array_agg(
            aggregate_order_by(
                ServiceDirectionRecord.departure_label,
                RouteDirectionRecord.sequence.asc(),
                ServiceDirectionRecord.sequence.asc(),
            )
        ),
        None,
    )
    return func.coalesce(labels, cast(array([], type_=Text()), ARRAY(Text()))).label("direction_hints")


def _route_candidate_hints_cte():
    return (
        select(
            RouteVersionRecord.id.label("route_version_id"),
            _route_candidate_hints_expression(),
        )
        .select_from(RouteVersionRecord)
        .outerjoin(RouteDirectionRecord, RouteDirectionRecord.route_version_id == RouteVersionRecord.id)
        .outerjoin(ServiceDirectionRecord, _public_service_direction_join_condition())
        .where(RouteVersionRecord.is_current == true())
        .group_by(RouteVersionRecord.id)
        .cte("route_candidate_hints")
    )


def _search_route_candidates_statement():
    query_pattern = bindparam("query_pattern", type_=Text())
    return (
        select(
            RouteRecord.id.label("route_id"),
            RouteVersionRecord.id.label("route_version_id"),
            RouteRecord.code.label("route_code"),
            RouteRecord.name.label("route_name"),
            _route_candidate_hints_expression(),
        )
        .select_from(RouteRecord)
        .join(RouteVersionRecord, RouteVersionRecord.route_id == RouteRecord.id)
        .outerjoin(RouteDirectionRecord, RouteDirectionRecord.route_version_id == RouteVersionRecord.id)
        .outerjoin(ServiceDirectionRecord, _public_service_direction_join_condition())
        .where(
            RouteRecord.is_current == true(),
            RouteVersionRecord.is_current == true(),
            or_(
                RouteRecord.code.ilike(query_pattern),
                RouteRecord.name.ilike(query_pattern),
            ),
        )
        .group_by(RouteRecord.id, RouteVersionRecord.id, RouteRecord.code, RouteRecord.name)
        .order_by(RouteRecord.code.asc(), RouteRecord.name.asc())
        .limit(bindparam("limit"))
    )


def _nearby_route_candidates_statement():
    user_point = _user_point_cte()
    distance = func.min(func.ST_Distance(_geography(RouteSegmentRecord.geometry), user_point.c.geog)).label(
        "distance_meters"
    )
    nearby_routes = (
        select(
            RouteRecord.id.label("route_id"),
            RouteVersionRecord.id.label("route_version_id"),
            RouteRecord.code.label("route_code"),
            RouteRecord.name.label("route_name"),
            distance,
        )
        .select_from(RouteRecord)
        .join(RouteVersionRecord, RouteVersionRecord.route_id == RouteRecord.id)
        .join(RouteDirectionRecord, RouteDirectionRecord.route_version_id == RouteVersionRecord.id)
        .join(
            RouteSegmentRecord,
            and_(
                RouteSegmentRecord.route_direction_id == RouteDirectionRecord.id,
                RouteSegmentRecord.route_version_id == RouteVersionRecord.id,
            ),
        )
        .join(user_point, true())
        .where(
            RouteRecord.is_current == true(),
            RouteVersionRecord.is_current == true(),
            func.ST_DWithin(
                _geography(RouteSegmentRecord.geometry),
                user_point.c.geog,
                bindparam("radius_meters"),
            ),
        )
        .group_by(RouteRecord.id, RouteVersionRecord.id, RouteRecord.code, RouteRecord.name)
        .order_by(distance.asc(), RouteRecord.code.asc(), RouteRecord.name.asc())
        .limit(bindparam("limit"))
        .cte("nearby_routes")
    )
    route_candidate_hints = _route_candidate_hints_cte()

    return (
        select(
            nearby_routes.c.route_id,
            nearby_routes.c.route_version_id,
            nearby_routes.c.route_code,
            nearby_routes.c.route_name,
            route_candidate_hints.c.direction_hints,
            nearby_routes.c.distance_meters,
        )
        .select_from(nearby_routes)
        .join(route_candidate_hints, route_candidate_hints.c.route_version_id == nearby_routes.c.route_version_id)
        .order_by(
            nearby_routes.c.distance_meters.asc(), nearby_routes.c.route_code.asc(), nearby_routes.c.route_name.asc()
        )
    )


def _nearby_route_directions_statement():
    user_point = _user_point_cte()
    distance = func.min(func.ST_Distance(_geography(RouteSegmentRecord.geometry), user_point.c.geog)).label(
        "distance_meters"
    )
    nearby_segments = (
        select(RouteSegmentRecord.route_direction_id.label("route_direction_id"), distance)
        .select_from(RouteSegmentRecord)
        .join(RouteVersionRecord, RouteVersionRecord.id == RouteSegmentRecord.route_version_id)
        .join(RouteRecord, RouteRecord.id == RouteVersionRecord.route_id)
        .join(user_point, true())
        .where(
            RouteRecord.is_current == true(),
            RouteVersionRecord.is_current == true(),
            func.ST_DWithin(
                _geography(RouteSegmentRecord.geometry),
                user_point.c.geog,
                bindparam("radius_meters"),
            ),
        )
        .group_by(RouteSegmentRecord.route_direction_id)
        .cte("nearby_segments")
    )
    candidate_labels = _direction_labels_cte("candidate_labels")

    return (
        select(
            RouteRecord.id.label("route_id"),
            RouteRecord.code.label("route_code"),
            RouteRecord.name.label("route_name"),
            RouteVersionRecord.id.label("route_version_id"),
            RouteDirectionRecord.id.label("route_direction_id"),
            RouteDirectionRecord.sequence.label("route_direction_sequence"),
            RouteDirectionRecord.name.label("route_direction_name"),
            candidate_labels.c.departure_labels,
            nearby_segments.c.distance_meters,
        )
        .select_from(nearby_segments)
        .join(RouteDirectionRecord, RouteDirectionRecord.id == nearby_segments.c.route_direction_id)
        .join(RouteVersionRecord, RouteVersionRecord.id == RouteDirectionRecord.route_version_id)
        .join(RouteRecord, RouteRecord.id == RouteVersionRecord.route_id)
        .join(candidate_labels, candidate_labels.c.route_direction_id == RouteDirectionRecord.id)
        .order_by(nearby_segments.c.distance_meters.asc(), RouteRecord.code.asc(), RouteDirectionRecord.sequence.asc())
        .limit(bindparam("limit"))
    )


def _list_current_routes_statement(*, has_location: bool):
    user_point = _user_point_cte() if has_location else None
    query_pattern = bindparam("query_pattern", type_=Text())
    distance = (
        func.min(func.ST_Distance(_geography(RouteSegmentRecord.geometry), user_point.c.geog)).label("distance_meters")
        if user_point is not None
        else cast(literal(None), Float).label("distance_meters")
    )

    matching_routes = (
        select(
            RouteRecord.id.label("route_id"),
            RouteRecord.code.label("route_code"),
            RouteRecord.name.label("route_name"),
            RouteVersionRecord.id.label("route_version_id"),
            distance,
        )
        .select_from(RouteRecord)
        .join(RouteVersionRecord, RouteVersionRecord.route_id == RouteRecord.id)
        .join(RouteDirectionRecord, RouteDirectionRecord.route_version_id == RouteVersionRecord.id)
        .where(
            RouteRecord.is_current == true(),
            RouteVersionRecord.is_current == true(),
            or_(
                query_pattern.is_(None),
                RouteRecord.code.ilike(query_pattern),
                RouteRecord.name.ilike(query_pattern),
            ),
        )
    )
    if user_point is not None:
        matching_routes = matching_routes.join(
            RouteSegmentRecord,
            RouteSegmentRecord.route_direction_id == RouteDirectionRecord.id,
        ).join(user_point, true())
        matching_routes = matching_routes.where(
            func.ST_DWithin(
                _geography(RouteSegmentRecord.geometry),
                user_point.c.geog,
                bindparam("radius_meters"),
            )
        )

    matching_routes = (
        matching_routes.group_by(RouteRecord.id, RouteRecord.code, RouteRecord.name, RouteVersionRecord.id)
        .order_by(distance.asc().nulls_last(), RouteRecord.code.asc(), RouteRecord.name.asc())
        .limit(bindparam("limit"))
        .cte("matching_routes")
    )
    direction_labels = _direction_labels_cte()

    return (
        select(
            matching_routes.c.route_id,
            matching_routes.c.route_code,
            matching_routes.c.route_name,
            matching_routes.c.route_version_id,
            matching_routes.c.distance_meters,
            RouteDirectionRecord.id.label("route_direction_id"),
            RouteDirectionRecord.sequence.label("route_direction_sequence"),
            RouteDirectionRecord.name.label("route_direction_name"),
            direction_labels.c.departure_labels,
        )
        .select_from(matching_routes)
        .join(RouteDirectionRecord, RouteDirectionRecord.route_version_id == matching_routes.c.route_version_id)
        .join(direction_labels, direction_labels.c.route_direction_id == RouteDirectionRecord.id)
        .order_by(
            matching_routes.c.distance_meters.asc().nulls_last(),
            matching_routes.c.route_code.asc(),
            matching_routes.c.route_name.asc(),
            RouteDirectionRecord.sequence.asc(),
        )
    )


def _load_current_route_statement():
    direction_labels = _direction_labels_cte()
    return (
        select(
            RouteRecord.id.label("route_id"),
            RouteRecord.code.label("route_code"),
            RouteRecord.name.label("route_name"),
            RouteVersionRecord.id.label("route_version_id"),
            cast(literal(None), Float).label("distance_meters"),
            RouteDirectionRecord.id.label("route_direction_id"),
            RouteDirectionRecord.sequence.label("route_direction_sequence"),
            RouteDirectionRecord.name.label("route_direction_name"),
            direction_labels.c.departure_labels,
        )
        .select_from(RouteRecord)
        .join(RouteVersionRecord, RouteVersionRecord.route_id == RouteRecord.id)
        .join(RouteDirectionRecord, RouteDirectionRecord.route_version_id == RouteVersionRecord.id)
        .join(direction_labels, direction_labels.c.route_direction_id == RouteDirectionRecord.id)
        .where(
            RouteRecord.is_current == true(),
            RouteVersionRecord.is_current == true(),
            RouteRecord.id == bindparam("route_id"),
        )
        .order_by(RouteDirectionRecord.sequence.asc())
    )


def _current_route_version_statement():
    return (
        select(RouteVersionRecord.id.label("route_version_id"))
        .select_from(RouteRecord)
        .join(RouteVersionRecord, RouteVersionRecord.route_id == RouteRecord.id)
        .where(
            RouteRecord.id == bindparam("route_id"),
            RouteRecord.is_current == true(),
            RouteVersionRecord.is_current == true(),
        )
    )


def _direction_choices_statement():
    direction_labels = _direction_labels_cte()
    return (
        select(
            RouteDirectionRecord.id.label("route_direction_id"),
            RouteDirectionRecord.sequence,
            RouteDirectionRecord.name,
            direction_labels.c.departure_labels,
        )
        .select_from(RouteDirectionRecord)
        .join(direction_labels, direction_labels.c.route_direction_id == RouteDirectionRecord.id)
        .where(RouteDirectionRecord.route_version_id == bindparam("route_version_id"))
        .order_by(RouteDirectionRecord.sequence.asc())
    )


def _route_direction_membership_statement():
    return select(RouteDirectionRecord.id).where(
        RouteDirectionRecord.route_version_id == bindparam("route_version_id"),
        RouteDirectionRecord.id == bindparam("route_direction_id"),
    )


def _load_current_route_segments_statement():
    return (
        select(
            RouteSegmentRecord.id,
            RouteSegmentRecord.sequence,
            func.ST_AsText(RouteSegmentRecord.geometry).label("geometry_wkt"),
            RouteSegmentRecord.bearing_degrees,
            RouteSegmentRecord.distance_meters,
            RouteSegmentRecord.cumulative_distance_meters,
        )
        .select_from(RouteSegmentRecord)
        .join(RouteDirectionRecord, RouteDirectionRecord.id == RouteSegmentRecord.route_direction_id)
        .join(RouteVersionRecord, RouteVersionRecord.id == RouteDirectionRecord.route_version_id)
        .join(RouteRecord, RouteRecord.id == RouteVersionRecord.route_id)
        .where(
            RouteRecord.is_current == true(),
            RouteVersionRecord.is_current == true(),
            RouteVersionRecord.id == bindparam("route_version_id"),
            RouteDirectionRecord.id == bindparam("route_direction_id"),
        )
        .order_by(RouteSegmentRecord.sequence.asc())
    )


def flatten_route_polyline(segments: list[RouteSegment]) -> list[LatLngPoint]:
    polyline: list[LatLngPoint] = []
    for segment in segments:
        for lng, lat in segment.coordinates:
            point = LatLngPoint(lat=lat, lng=lng)
            if polyline and polyline[-1] == point:
                continue
            polyline.append(point)
    return polyline


def _route_summaries_from_rows(rows) -> list[RouteSummary]:
    summaries: dict[UUID, RouteSummary] = {}
    for row in rows:
        values = row._mapping
        route_id = values["route_id"]
        summary = summaries.get(route_id)
        if summary is None:
            summary = RouteSummary(
                route_id=values["route_id"],
                route_code=values["route_code"],
                route_name=values["route_name"],
                route_version_id=values["route_version_id"],
                distance_meters=values["distance_meters"],
                directions=[],
            )
            summaries[route_id] = summary
        summary.directions.append(
            LightweightRouteDirection(
                route_direction_id=values["route_direction_id"],
                sequence=values["route_direction_sequence"],
                name=values["route_direction_name"],
                departure_labels=_dedupe_preserving_order(values["departure_labels"] or []),
            )
        )
    return list(summaries.values())


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _route_candidates_from_rows(rows) -> list[RouteCandidate]:
    candidates: list[RouteCandidate] = []
    for row in rows:
        values = row._mapping
        candidates.append(
            RouteCandidate(
                route_id=values["route_id"],
                route_version_id=values["route_version_id"],
                route_code=values["route_code"],
                route_name=values["route_name"],
                direction_hints=_dedupe_preserving_order(values["direction_hints"] or []),
                distance_meters=values["distance_meters"] if "distance_meters" in values else None,
            )
        )
    return candidates
