"""Live scrape CLI operating policy against the Generation Store seam."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sombreado.ingestion.scrape import ScrapeCollection, run_scrape
from sombreado.store.generation import CanonicalRows, GenerationStore
from sombreado.store.sample_data import sample_generation_rows


@dataclass
class FakeSource:
    collections: list[ScrapeCollection]
    calls: int = 0

    def collect(self) -> ScrapeCollection:
        index = min(self.calls, len(self.collections) - 1)
        self.calls += 1
        return self.collections[index]


@dataclass
class RaisingThenOkSource:
    error: Exception
    ok: ScrapeCollection
    calls: int = 0

    def collect(self) -> ScrapeCollection:
        self.calls += 1
        if self.calls == 1:
            raise self.error
        return self.ok


def _seed_current(store: GenerationStore, suffix: str = "a") -> CanonicalRows:
    rows = sample_generation_rows(generation_suffix=suffix)
    store.stage(f"gen-{suffix}", rows)
    store.validate(f"gen-{suffix}")
    store.publish(f"gen-{suffix}")
    return rows


def test_active_lease_fails_fast_without_force(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    _seed_current(store)
    store.claim_scrape_lease("other-worker", ttl_seconds=600)

    source = FakeSource(
        [
            ScrapeCollection(
                rows=sample_generation_rows(generation_suffix="b"),
                hard_failures=(),
                warnings=(),
            )
        ]
    )

    outcome = run_scrape(store, source, force=False, holder_id="cli-1")

    assert outcome.status == "lease_held"
    assert store.current_generation() == "gen-a"
    assert store.scrape_lease_holder() == "other-worker"
    assert source.calls == 0


def test_hard_failure_discards_staging_and_keeps_current(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    _seed_current(store)

    source = FakeSource(
        [
            ScrapeCollection(
                rows=sample_generation_rows(generation_suffix="b"),
                hard_failures=("https://example.test/horarios/still-listed,999",),
                warnings=(),
            )
        ]
    )

    outcome = run_scrape(store, source, holder_id="cli-1", retry_backoff_seconds=0)

    assert outcome.status == "failed"
    assert store.current_generation() == "gen-a"
    assert store.previous_generation() is None
    assert not store.has_generation("gen-b")
    # no leftover staging from the failed attempt
    with sqlite3.connect(store.database_path) as connection:
        staging = connection.execute(
            "SELECT COUNT(*) FROM dataset_generations WHERE status IN ('staging', 'validated')"
        ).fetchone()[0]
    assert staging == 0


def test_successful_scrape_publishes_new_current(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    _seed_current(store)

    source = FakeSource(
        [
            ScrapeCollection(
                rows=sample_generation_rows(generation_suffix="b"),
                hard_failures=(),
                warnings=("stop_adapter=unavailable",),
            )
        ]
    )

    outcome = run_scrape(store, source, holder_id="cli-1")

    assert outcome.status == "published"
    assert store.current_generation() == outcome.generation_id
    assert store.previous_generation() == "gen-a"
    assert store.scrape_lease_holder() is None


def test_force_reclaims_active_lease_and_discards_incomplete_staging(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    _seed_current(store)
    store.stage("orphan", sample_generation_rows(generation_suffix="orphan"))
    store.claim_scrape_lease("stale-worker", ttl_seconds=600)

    source = FakeSource(
        [
            ScrapeCollection(
                rows=sample_generation_rows(generation_suffix="b"),
                hard_failures=(),
                warnings=(),
            )
        ]
    )

    outcome = run_scrape(store, source, force=True, holder_id="cli-1")

    assert outcome.status == "published"
    assert store.current_generation() == outcome.generation_id
    assert not store.has_generation("orphan")
    assert store.scrape_lease_holder() is None


def test_one_automatic_retry_after_collect_failure(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    _seed_current(store)

    source = RaisingThenOkSource(
        error=RuntimeError("transient fetch boom"),
        ok=ScrapeCollection(
            rows=sample_generation_rows(generation_suffix="b"),
            hard_failures=(),
            warnings=(),
        ),
    )

    outcome = run_scrape(store, source, holder_id="cli-1", retry_backoff_seconds=0)

    assert outcome.status == "published"
    assert source.calls == 2
    assert store.current_generation() == outcome.generation_id


def test_scrape_run_metadata_recorded_and_pruned(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    _seed_current(store)

    source = FakeSource(
        [
            ScrapeCollection(
                rows=sample_generation_rows(generation_suffix="b"),
                hard_failures=(),
                warnings=("soft",),
            )
        ]
    )

    # Seed an old run row that should be pruned.
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            """
            INSERT INTO scrape_runs(
                id, started_at, finished_at, outcome, generation_id,
                route_count, warning_count, error_summary
            )
            VALUES (
                'old-run', '2000-01-01T00:00:00+00:00', '2000-01-01T00:01:00+00:00',
                'failed', NULL, 0, 0, 'ancient'
            )
            """
        )
        connection.commit()

    outcome = run_scrape(
        store,
        source,
        holder_id="cli-1",
        scrape_run_retention_days=30,
    )

    assert outcome.status == "published"
    with sqlite3.connect(store.database_path) as connection:
        rows = connection.execute(
            "SELECT id, outcome, route_count, warning_count FROM scrape_runs ORDER BY started_at"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "published"
    assert rows[0][2] == 1
    assert rows[0][3] == 1
