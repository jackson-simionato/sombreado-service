"""Add short-horizon scrape_runs metadata table.

Revision ID: 20260730_0002
Revises: 20260730_0001
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260730_0002"
down_revision: str | None = "20260730_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE scrape_runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
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
    op.execute("CREATE INDEX scrape_runs_started_at_idx ON scrape_runs(started_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS scrape_runs_started_at_idx")
    op.execute("DROP TABLE IF EXISTS scrape_runs")
