"""Generation-keyed SQLite store: lease, validate-then-publish, retention."""

import sqlite3
from pathlib import Path

import pytest

from sombreado.store.generation import GenerationStore, ScrapeLeaseHeldError
from sombreado.store.sample_data import sample_generation_rows


def test_migrate_leaves_no_current_generation(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()

    assert store.current_generation() is None
    assert store.previous_generation() is None


def test_validate_then_publish_flips_current_atomically(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    rows = sample_generation_rows(generation_suffix="a")

    store.stage("gen-a", rows)
    assert store.current_generation() is None

    store.validate("gen-a")
    assert store.current_generation() is None

    store.publish("gen-a")
    assert store.current_generation() == "gen-a"
    assert store.previous_generation() is None
    assert set(store.current_route_version_ids()) == {row["id"] for row in rows["route_versions"]}


def test_second_publish_retains_previous_and_drops_former_previous(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()

    store.stage("gen-a", sample_generation_rows(generation_suffix="a"))
    store.validate("gen-a")
    store.publish("gen-a")

    store.stage("gen-b", sample_generation_rows(generation_suffix="b"))
    store.validate("gen-b")
    store.publish("gen-b")

    assert store.current_generation() == "gen-b"
    assert store.previous_generation() == "gen-a"

    store.stage("gen-c", sample_generation_rows(generation_suffix="c"))
    store.validate("gen-c")
    store.publish("gen-c")

    assert store.current_generation() == "gen-c"
    assert store.previous_generation() == "gen-b"
    assert not store.has_generation("gen-a")


def test_incomplete_staging_cannot_publish(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    store.stage("gen-a", sample_generation_rows(generation_suffix="a"))
    store.validate("gen-a")
    store.publish("gen-a")

    store.stage("gen-b", sample_generation_rows(generation_suffix="b"))

    with pytest.raises(RuntimeError, match="not validated"):
        store.publish("gen-b")

    assert store.current_generation() == "gen-a"
    assert store.previous_generation() is None


def test_validation_failure_discards_staging_and_keeps_current(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    good = sample_generation_rows(generation_suffix="a")
    store.stage("gen-a", good)
    store.validate("gen-a")
    store.publish("gen-a")

    store.stage("gen-b", sample_generation_rows(generation_suffix="b"))
    # Corrupt expected counts after stage so validate rejects before publish.
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            """
            UPDATE dataset_generation_counts
            SET route_segments = route_segments + 1
            WHERE generation_id = 'gen-b'
            """
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="counts do not match"):
        store.validate("gen-b")

    assert store.current_generation() == "gen-a"
    assert store.previous_generation() is None
    assert not store.has_generation("gen-b")


def test_expired_lease_reclaim_discards_orphan_staging(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    store.stage("gen-a", sample_generation_rows(generation_suffix="a"))
    store.validate("gen-a")
    store.publish("gen-a")
    store.stage("orphan", sample_generation_rows(generation_suffix="b"))

    store.claim_scrape_lease("worker-1", ttl_seconds=1)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            """
            UPDATE scrape_lease
            SET expires_at = ?
            WHERE singleton = 1
            """,
            ("2000-01-01T00:00:00+00:00",),
        )
        connection.commit()

    store.claim_scrape_lease("worker-2", ttl_seconds=600)

    assert store.scrape_lease_holder() == "worker-2"
    assert store.current_generation() == "gen-a"
    assert not store.has_generation("orphan")


def test_scrape_lease_excludes_overlapping_holders(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()

    store.claim_scrape_lease("worker-1", ttl_seconds=600)
    with pytest.raises(ScrapeLeaseHeldError):
        store.claim_scrape_lease("worker-2", ttl_seconds=600)

    store.release_scrape_lease("worker-1")
    store.claim_scrape_lease("worker-2", ttl_seconds=600)
    assert store.scrape_lease_holder() == "worker-2"
