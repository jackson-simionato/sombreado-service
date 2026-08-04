"""Fresh Neon/PostGIS Generation Store schema (geography nearby, lease, generations).

Revision ID: 20260731_0001
Revises:
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
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
            public_id TEXT PRIMARY KEY,
            route_version_id TEXT NOT NULL REFERENCES route_versions(id),
            route_direction_id TEXT NOT NULL REFERENCES route_directions(id),
            sequence INTEGER NOT NULL,
            source_segment_sequence INTEGER NOT NULL,
            source_fraction_start DOUBLE PRECISION NOT NULL,
            source_fraction_end DOUBLE PRECISION NOT NULL,
            geometry TEXT NOT NULL,
            geom geography(LINESTRING, 4326) NOT NULL,
            bearing_degrees DOUBLE PRECISION NOT NULL,
            distance_meters DOUBLE PRECISION NOT NULL,
            cumulative_distance_meters DOUBLE PRECISION NOT NULL,
            UNIQUE (route_version_id, route_direction_id, sequence)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE dataset_generations (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN ('staging', 'validated', 'published')),
            created_at TIMESTAMPTZ NOT NULL,
            validated_at TIMESTAMPTZ
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
        CREATE TABLE generation_routes (
            generation_id TEXT NOT NULL REFERENCES dataset_generations(id),
            route_id TEXT NOT NULL REFERENCES routes(id),
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            slug TEXT NOT NULL,
            category TEXT,
            fare_region TEXT,
            last_changed TEXT,
            is_current INTEGER NOT NULL CHECK (is_current IN (0, 1)),
            PRIMARY KEY (generation_id, route_id)
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
            singleton SMALLINT PRIMARY KEY CHECK (singleton = 1),
            holder_id TEXT NOT NULL,
            claimed_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE scrape_runs (
            id TEXT PRIMARY KEY,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ,
            outcome TEXT NOT NULL CHECK (
                outcome IN ('published', 'failed', 'lease_held')
            ),
            generation_id TEXT,
            route_count INTEGER NOT NULL DEFAULT 0,
            warning_count INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT
        )
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
    op.execute("CREATE INDEX route_segments_geom_gix ON route_segments USING GIST (geom)")
    op.execute("CREATE INDEX dataset_route_versions_version_idx ON dataset_route_versions(route_version_id)")
    op.execute("CREATE INDEX scrape_runs_started_at_idx ON scrape_runs(started_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS scrape_runs_started_at_idx")
    op.execute("DROP INDEX IF EXISTS dataset_route_versions_version_idx")
    op.execute("DROP INDEX IF EXISTS route_segments_geom_gix")
    op.execute("DROP INDEX IF EXISTS route_segments_version_direction_sequence_idx")
    op.execute("DROP INDEX IF EXISTS service_directions_direction_sequence_idx")
    op.execute("DROP INDEX IF EXISTS route_directions_version_sequence_idx")
    op.execute("DROP INDEX IF EXISTS route_versions_route_id_idx")
    op.execute("DROP TABLE IF EXISTS scrape_runs")
    op.execute("DROP TABLE IF EXISTS scrape_lease")
    op.execute("DROP TABLE IF EXISTS dataset_pointers")
    op.execute("DROP TABLE IF EXISTS generation_routes")
    op.execute("DROP TABLE IF EXISTS dataset_generation_counts")
    op.execute("DROP TABLE IF EXISTS dataset_route_versions")
    op.execute("DROP TABLE IF EXISTS dataset_generations")
    op.execute("DROP TABLE IF EXISTS route_segments")
    op.execute("DROP TABLE IF EXISTS service_directions")
    op.execute("DROP TABLE IF EXISTS route_directions")
    op.execute("DROP TABLE IF EXISTS route_versions")
    op.execute("DROP TABLE IF EXISTS routes")
