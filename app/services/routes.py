from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.schemas import CandidateRouteDirection, LightweightRouteDirection, RouteSegment, RouteSummary
from app.services.geometry import parse_linestring_wkt

logger = get_logger(__name__)


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
            text(
                """
                WITH user_point AS (
                  SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS geog
                ),
                nearby_segments AS (
                  SELECT
                    rs.route_direction_id,
                    MIN(ST_Distance(rs.geometry::geography, user_point.geog)) AS distance_meters
                  FROM route_segments rs
                  JOIN route_versions rv ON rv.id = rs.route_version_id
                  JOIN routes r ON r.id = rv.route_id
                  CROSS JOIN user_point
                  WHERE r.is_current = true
                    AND rv.is_current = true
                    AND ST_DWithin(rs.geometry::geography, user_point.geog, :radius_meters)
                  GROUP BY rs.route_direction_id
                ),
                candidate_labels AS (
                  SELECT
                    rd.id AS route_direction_id,
                    COALESCE(
                      array_remove(array_agg(DISTINCT sd.departure_label ORDER BY sd.departure_label), NULL),
                      ARRAY[]::text[]
                    ) AS departure_labels
                  FROM route_directions rd
                  LEFT JOIN service_directions sd ON sd.route_direction_id = rd.id
                  GROUP BY rd.id
                )
                SELECT
                  r.id AS route_id,
                  r.code AS route_code,
                  r.name AS route_name,
                  rv.id AS route_version_id,
                  rd.id AS route_direction_id,
                  rd.sequence AS route_direction_sequence,
                  rd.name AS route_direction_name,
                  cl.departure_labels,
                  ns.distance_meters
                FROM nearby_segments ns
                JOIN route_directions rd ON rd.id = ns.route_direction_id
                JOIN route_versions rv ON rv.id = rd.route_version_id
                JOIN routes r ON r.id = rv.route_id
                JOIN candidate_labels cl ON cl.route_direction_id = rd.id
                ORDER BY ns.distance_meters ASC, r.code ASC, rd.sequence ASC
                LIMIT :limit
                """
            ),
            {"lat": lat, "lng": lng, "radius_meters": radius_meters, "limit": limit},
        )
        return [CandidateRouteDirection.model_validate(row._mapping) for row in rows]

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
            text(
                """
                WITH matching_routes AS (
                  SELECT
                    r.id AS route_id,
                    r.code AS route_code,
                    r.name AS route_name,
                    rv.id AS route_version_id,
                    CASE
                      WHEN :has_location THEN MIN(ST_Distance(rs.geometry::geography, user_point.geog))
                      ELSE NULL
                    END AS distance_meters
                  FROM routes r
                  JOIN route_versions rv ON rv.route_id = r.id
                  JOIN route_directions rd ON rd.route_version_id = rv.id
                  LEFT JOIN route_segments rs ON rs.route_direction_id = rd.id
                  LEFT JOIN LATERAL (
                    SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS geog
                  ) user_point ON :has_location
                  WHERE r.is_current = true
                    AND rv.is_current = true
                    AND (:query_pattern IS NULL OR r.code ILIKE :query_pattern OR r.name ILIKE :query_pattern)
                    AND (
                      NOT :has_location
                      OR ST_DWithin(rs.geometry::geography, user_point.geog, :radius_meters)
                    )
                  GROUP BY r.id, r.code, r.name, rv.id
                  ORDER BY
                    CASE
                      WHEN :has_location THEN MIN(ST_Distance(rs.geometry::geography, user_point.geog))
                    END ASC NULLS LAST,
                    r.code ASC,
                    r.name ASC
                  LIMIT :limit
                ),
                direction_labels AS (
                  SELECT
                    rd.id AS route_direction_id,
                    COALESCE(
                      array_remove(array_agg(DISTINCT sd.departure_label ORDER BY sd.departure_label), NULL),
                      ARRAY[]::text[]
                    ) AS departure_labels
                  FROM route_directions rd
                  LEFT JOIN service_directions sd ON sd.route_direction_id = rd.id
                  GROUP BY rd.id
                )
                SELECT
                  mr.route_id,
                  mr.route_code,
                  mr.route_name,
                  mr.route_version_id,
                  mr.distance_meters,
                  rd.id AS route_direction_id,
                  rd.sequence AS route_direction_sequence,
                  rd.name AS route_direction_name,
                  dl.departure_labels
                FROM matching_routes mr
                JOIN route_directions rd ON rd.route_version_id = mr.route_version_id
                JOIN direction_labels dl ON dl.route_direction_id = rd.id
                ORDER BY
                  mr.distance_meters ASC NULLS LAST,
                  mr.route_code ASC,
                  mr.route_name ASC,
                  rd.sequence ASC
                """
            ),
            {
                "query_pattern": f"%{query}%" if query else None,
                "lat": lat,
                "lng": lng,
                "radius_meters": radius_meters,
                "has_location": has_location,
                "limit": limit,
            },
        )
        return _route_summaries_from_rows(rows)

    async def load_current_route_segments(
        self,
        *,
        route_version_id: UUID,
        route_direction_id: UUID,
    ) -> list[RouteSegment]:
        rows = await self._session.execute(
            text(
                """
                SELECT
                  rs.id,
                  rs.sequence,
                  ST_AsText(rs.geometry) AS geometry_wkt,
                  rs.bearing_degrees,
                  rs.distance_meters,
                  rs.cumulative_distance_meters
                FROM route_segments rs
                JOIN route_directions rd ON rd.id = rs.route_direction_id
                JOIN route_versions rv ON rv.id = rd.route_version_id
                JOIN routes r ON r.id = rv.route_id
                WHERE r.is_current = true
                  AND rv.is_current = true
                  AND rv.id = :route_version_id
                  AND rd.id = :route_direction_id
                ORDER BY rs.sequence ASC
                """
            ),
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
                departure_labels=values["departure_labels"],
            )
        )
    return list(summaries.values())
