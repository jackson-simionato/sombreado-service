"""Add route_directions.advice_segments JSONB denorm for passenger advice.

Revision ID: 20260815_0002
Revises: 20260731_0001
Create Date: 2026-08-15
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260815_0002"
down_revision: str | None = "20260731_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINESTRING_RE = re.compile(
    r"LINESTRING\s*\((.*)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _coords_from_segment_geometry(value: str) -> list[list[float]]:
    wkt = value.split(";", 1)[-1].strip()
    match = _LINESTRING_RE.search(wkt)
    if match is None:
        raise ValueError(f"unsupported linestring geometry: {value}")
    coords: list[list[float]] = []
    for point_text in match.group(1).split(","):
        lon_text, lat_text = point_text.strip().split()[:2]
        coords.append([float(lon_text), float(lat_text)])
    return coords


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE route_directions
        ADD COLUMN advice_segments JSONB NOT NULL DEFAULT '[]'::jsonb
        """
    )
    conn = op.get_bind()
    directions = conn.execute(text("SELECT id FROM route_directions")).fetchall()
    for (direction_id,) in directions:
        segments = conn.execute(
            text(
                """
                SELECT public_id, sequence, geometry, bearing_degrees,
                       distance_meters, cumulative_distance_meters
                FROM route_segments
                WHERE route_direction_id = :id
                ORDER BY sequence ASC
                """
            ),
            {"id": direction_id},
        ).fetchall()
        payload = [
            {
                "public_id": public_id,
                "sequence": sequence,
                "coordinates": _coords_from_segment_geometry(geometry),
                "bearing_degrees": float(bearing),
                "distance_meters": float(distance),
                "cumulative_distance_meters": float(cumulative),
            }
            for public_id, sequence, geometry, bearing, distance, cumulative in segments
        ]
        conn.execute(
            text(
                """
                UPDATE route_directions
                SET advice_segments = CAST(:payload AS jsonb)
                WHERE id = :id
                """
            ),
            {"id": direction_id, "payload": json.dumps(payload)},
        )


def downgrade() -> None:
    op.execute("ALTER TABLE route_directions DROP COLUMN advice_segments")
