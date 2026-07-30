"""Publish a fixture/snapshot generation into the SQLite store without Consórcio."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from sombreado.store.generation import CanonicalRows, GenerationStore
from sombreado.store.sample_data import sample_generation_rows


def load_canonical_rows(path: Path) -> CanonicalRows:
    """Load canonical generation rows from a JSON object keyed by table name."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("fixture must be a JSON object of table -> rows")
    return payload


def publish_fixture(
    store: GenerationStore,
    rows: CanonicalRows,
    *,
    generation_id: str | None = None,
    lease_holder: str = "fixture-publish",
) -> str:
    """Migrate, lease, stage, validate, and publish rows; return the generation id."""
    store.migrate()
    store.claim_scrape_lease(lease_holder)
    try:
        published_id = generation_id or f"fixture-{uuid4()}"
        store.stage(published_id, rows)
        store.validate(published_id)
        store.publish(published_id)
        return published_id
    finally:
        store.release_scrape_lease(lease_holder)


def publish_demo_fixture(
    database_path: Path,
    *,
    fixture_path: Path | None = None,
    generation_id: str | None = None,
) -> tuple[str, GenerationStore]:
    """Publish either an explicit JSON fixture or the built-in demo sample."""
    store = GenerationStore(database_path)
    rows = (
        load_canonical_rows(fixture_path)
        if fixture_path is not None
        else sample_generation_rows(generation_suffix="demo")
    )
    published_id = publish_fixture(store, rows, generation_id=generation_id)
    return published_id, store
