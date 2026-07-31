"""Generation-keyed PostGIS store: lease, validate-then-publish, retention."""

from datetime import UTC, datetime, timedelta

import pytest

from sombreado.store.generation import GenerationStore, ScrapeLeaseHeldError
from sombreado.store.sample_data import sample_generation_rows


def test_migrate_leaves_no_current_generation(store: GenerationStore):
    assert store.current_generation() is None
    assert store.previous_generation() is None


def test_validate_then_publish_flips_current_atomically(store: GenerationStore):
    rows = sample_generation_rows(generation_suffix="a")

    store.stage("gen-a", rows)
    assert store.current_generation() is None

    store.validate("gen-a")
    assert store.current_generation() is None

    store.publish("gen-a")
    assert store.current_generation() == "gen-a"
    assert store.previous_generation() is None
    assert set(store.current_route_version_ids()) == {row["id"] for row in rows["route_versions"]}


def test_second_publish_retains_previous_and_drops_former_previous(store: GenerationStore):
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


def test_incomplete_staging_cannot_publish(store: GenerationStore):
    store.stage("gen-a", sample_generation_rows(generation_suffix="a"))
    store.validate("gen-a")
    store.publish("gen-a")

    store.stage("gen-b", sample_generation_rows(generation_suffix="b"))

    with pytest.raises(RuntimeError, match="not validated"):
        store.publish("gen-b")

    assert store.current_generation() == "gen-a"
    assert store.previous_generation() is None


def test_validation_failure_discards_staging_and_keeps_current(store: GenerationStore):
    good = sample_generation_rows(generation_suffix="a")
    store.stage("gen-a", good)
    store.validate("gen-a")
    store.publish("gen-a")

    store.stage("gen-b", sample_generation_rows(generation_suffix="b"))
    # Corrupt expected counts after stage so validate rejects before publish.
    with store.connection() as connection:
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


def test_expired_lease_reclaim_discards_orphan_staging(store: GenerationStore):
    store.stage("gen-a", sample_generation_rows(generation_suffix="a"))
    store.validate("gen-a")
    store.publish("gen-a")
    store.stage("orphan", sample_generation_rows(generation_suffix="b"))

    store.claim_scrape_lease("worker-1", ttl_seconds=1)
    with store.connection() as connection:
        connection.execute(
            """
            UPDATE scrape_lease
            SET expires_at = %(past)s
            WHERE singleton = 1
            """,
            {"past": datetime.now(UTC) - timedelta(seconds=1)},
        )
        connection.commit()

    store.claim_scrape_lease("worker-2", ttl_seconds=600)

    assert store.scrape_lease_holder() == "worker-2"
    assert store.current_generation() == "gen-a"
    assert not store.has_generation("orphan")


def test_scrape_lease_excludes_overlapping_holders(store: GenerationStore):
    store.claim_scrape_lease("worker-1", ttl_seconds=600)
    with pytest.raises(ScrapeLeaseHeldError):
        store.claim_scrape_lease("worker-2", ttl_seconds=600)

    store.release_scrape_lease("worker-1")
    store.claim_scrape_lease("worker-2", ttl_seconds=600)
    assert store.scrape_lease_holder() == "worker-2"


def _stable_route_rows(*, generation_suffix: str, route_name: str) -> dict[str, list[dict[str, object]]]:
    """Same stable route id across generations; only version/name content varies."""
    rows = sample_generation_rows(generation_suffix=generation_suffix)
    route_id = "route-stable"
    rows["routes"] = [
        {
            **rows["routes"][0],
            "id": route_id,
            "code": "110",
            "name": route_name,
            "slug": "route-110",
        }
    ]
    for version in rows["route_versions"]:
        version["route_id"] = route_id
    return rows


def test_stage_does_not_mutate_shared_route_attributes_until_publish(store: GenerationStore):
    store.stage("gen-a", _stable_route_rows(generation_suffix="a", route_name="Old Name"))
    store.validate("gen-a")
    store.publish("gen-a")

    store.stage("gen-b", _stable_route_rows(generation_suffix="b", route_name="Staged Name"))

    with store.connection() as connection:
        name = connection.execute("SELECT name FROM routes WHERE id = 'route-stable'").fetchone()[0]
    assert name == "Old Name"

    store.discard_staging("gen-b")
    with store.connection() as connection:
        name = connection.execute("SELECT name FROM routes WHERE id = 'route-stable'").fetchone()[0]
    assert name == "Old Name"

    store.stage("gen-c", _stable_route_rows(generation_suffix="c", route_name="Published Name"))
    store.validate("gen-c")
    store.publish("gen-c")
    with store.connection() as connection:
        name = connection.execute("SELECT name FROM routes WHERE id = 'route-stable'").fetchone()[0]
    assert name == "Published Name"


def test_expected_counts_include_non_current_membership_versions(store: GenerationStore):
    rows = sample_generation_rows(generation_suffix="a")
    rows["routes"].append(
        {
            "id": "route-legacy",
            "code": "999",
            "name": "Legacy",
            "slug": "route-999",
            "category": "conventional",
            "fare_region": None,
            "last_changed": None,
            "is_current": 0,
        }
    )
    rows["route_versions"].append(
        {
            "id": "version-legacy",
            "route_id": "route-legacy",
            "source_hash": "legacy",
            "map_hash": None,
            "page_url": "https://example.test/legacy",
            "map_url": None,
            "is_current": 0,
        }
    )

    store.stage("gen-a", rows)
    store.validate("gen-a")
    store.publish("gen-a")
    assert store.current_generation() == "gen-a"
    assert "version-legacy" in store.current_route_version_ids()


def test_force_lease_reclaim_discards_orphan_staging(store: GenerationStore):
    store.stage("gen-a", sample_generation_rows(generation_suffix="a"))
    store.validate("gen-a")
    store.publish("gen-a")
    store.stage("orphan", sample_generation_rows(generation_suffix="b"))
    store.claim_scrape_lease("worker-1", ttl_seconds=600)

    store.claim_scrape_lease("worker-2", ttl_seconds=600, force=True)

    assert store.scrape_lease_holder() == "worker-2"
    assert store.current_generation() == "gen-a"
    assert not store.has_generation("orphan")
