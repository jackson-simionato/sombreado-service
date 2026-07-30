"""Create Generation Store schema (routes, generations, R*Tree, lease).

Revision ID: 20260730_0001
Revises:
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260730_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE routes (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            slug TEXT NOT NULL,
            category TEXT,
            fare_region TEXT,
            last_changed TEXT,
            is_current INTEGER NOT NULL CHECK (is_current IN (0, 1))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE route_versions (
            id TEXT PRIMARY KEY,
            route_id TEXT NOT NULL REFERENCES routes(id),
            source_hash TEXT NOT NULL,
            map_hash TEXT,
            page_url TEXT NOT NULL,
            map_url TEXT,
            is_current INTEGER NOT NULL CHECK (is_current IN (0, 1))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE route_directions (
            id TEXT PRIMARY KEY,
            route_version_id TEXT NOT NULL REFERENCES route_versions(id),
            name TEXT NOT NULL,
            direction_kind TEXT,
            sequence INTEGER NOT NULL,
            geometry TEXT NOT NULL,
            UNIQUE (route_version_id, sequence)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE service_directions (
            id TEXT PRIMARY KEY,
            route_version_id TEXT NOT NULL REFERENCES route_versions(id),
            route_direction_id TEXT REFERENCES route_directions(id),
            sequence INTEGER NOT NULL,
            departure_label TEXT NOT NULL,
            normalized_name TEXT,
            direction_kind TEXT,
            confidence TEXT NOT NULL,
            method TEXT NOT NULL,
            notes TEXT NOT NULL,
            UNIQUE (route_version_id, departure_label)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE route_segments (
            segment_rowid INTEGER PRIMARY KEY,
            public_id TEXT NOT NULL UNIQUE,
            route_version_id TEXT NOT NULL REFERENCES route_versions(id),
            route_direction_id TEXT NOT NULL REFERENCES route_directions(id),
            sequence INTEGER NOT NULL,
            source_segment_sequence INTEGER NOT NULL,
            source_fraction_start REAL NOT NULL,
            source_fraction_end REAL NOT NULL,
            geometry TEXT NOT NULL,
            bearing_degrees REAL NOT NULL,
            distance_meters REAL NOT NULL,
            cumulative_distance_meters REAL NOT NULL,
            start_lng REAL NOT NULL,
            start_lat REAL NOT NULL,
            end_lng REAL NOT NULL,
            end_lat REAL NOT NULL,
            min_lng REAL NOT NULL,
            max_lng REAL NOT NULL,
            min_lat REAL NOT NULL,
            max_lat REAL NOT NULL,
            UNIQUE (route_version_id, route_direction_id, sequence)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE dataset_generations (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN ('staging', 'validated', 'published')),
            created_at TEXT NOT NULL,
            validated_at TEXT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE dataset_route_versions (
            generation_id TEXT NOT NULL REFERENCES dataset_generations(id),
            route_id TEXT NOT NULL REFERENCES routes(id),
            route_version_id TEXT NOT NULL REFERENCES route_versions(id),
            PRIMARY KEY (generation_id, route_id),
            UNIQUE (generation_id, route_version_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE dataset_generation_counts (
            generation_id TEXT PRIMARY KEY REFERENCES dataset_generations(id),
            route_versions INTEGER NOT NULL,
            route_directions INTEGER NOT NULL,
            service_directions INTEGER NOT NULL,
            route_segments INTEGER NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE dataset_pointers (
            role TEXT PRIMARY KEY CHECK (role IN ('current', 'previous')),
            generation_id TEXT NOT NULL REFERENCES dataset_generations(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE scrape_lease (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            holder_id TEXT NOT NULL,
            claimed_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE VIRTUAL TABLE segment_rtree
        USING rtree(segment_rowid, min_lng, max_lng, min_lat, max_lat)
        """
    )
    op.execute("CREATE INDEX route_versions_route_id_idx ON route_versions(route_id)")
    op.execute("CREATE INDEX route_directions_version_sequence_idx ON route_directions(route_version_id, sequence)")
    op.execute(
        "CREATE INDEX service_directions_direction_sequence_idx ON service_directions(route_direction_id, sequence)"
    )
    op.execute(
        """
        CREATE INDEX route_segments_version_direction_sequence_idx
        ON route_segments(route_version_id, route_direction_id, sequence)
        """
    )
    op.execute("CREATE INDEX dataset_route_versions_version_idx ON dataset_route_versions(route_version_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS dataset_route_versions_version_idx")
    op.execute("DROP INDEX IF EXISTS route_segments_version_direction_sequence_idx")
    op.execute("DROP INDEX IF EXISTS service_directions_direction_sequence_idx")
    op.execute("DROP INDEX IF EXISTS route_directions_version_sequence_idx")
    op.execute("DROP INDEX IF EXISTS route_versions_route_id_idx")
    op.execute("DROP TABLE IF EXISTS segment_rtree")
    op.execute("DROP TABLE IF EXISTS scrape_lease")
    op.execute("DROP TABLE IF EXISTS dataset_pointers")
    op.execute("DROP TABLE IF EXISTS dataset_generation_counts")
    op.execute("DROP TABLE IF EXISTS dataset_route_versions")
    op.execute("DROP TABLE IF EXISTS dataset_generations")
    op.execute("DROP TABLE IF EXISTS route_segments")
    op.execute("DROP TABLE IF EXISTS service_directions")
    op.execute("DROP TABLE IF EXISTS route_directions")
    op.execute("DROP TABLE IF EXISTS route_versions")
    op.execute("DROP TABLE IF EXISTS routes")
