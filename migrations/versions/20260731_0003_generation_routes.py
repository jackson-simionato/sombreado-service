"""Store generation-scoped route attributes applied only at publish.

Revision ID: 20260731_0003
Revises: 20260730_0002
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0003"
down_revision: str | None = "20260730_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS generation_routes")
