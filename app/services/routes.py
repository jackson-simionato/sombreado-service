from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.schemas import CandidateRouteDirection, RouteSegment
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
        logger.info("Finding nearby route directions lat=%s lng=%s radius_meters=%s limit=%s", lat, lng, radius_meters, limit)
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
                      MIN(sd.departure_label) FILTER (WHERE sd.departure_label IS NOT NULL),
                      rd.name
                    ) AS candidate_direction_label
                  FROM route_directions rd
                  LEFT JOIN service_directions sd ON sd.route_direction_id = rd.id
                  GROUP BY rd.id, rd.name
                )
                SELECT
                  r.id AS route_id,
                  r.code AS route_code,
                  r.name AS route_name,
                  rv.id AS route_version_id,
                  rd.id AS route_direction_id,
                  rd.sequence AS route_direction_sequence,
                  cl.candidate_direction_label,
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

    async def load_current_route_segments(self, *, route_version_id: UUID, route_direction_id: UUID) -> list[RouteSegment]:
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
