"""Live scrape CLI operating policy against the Generation Store seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

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


def test_active_lease_fails_fast_without_force(database_url: str):
    store = GenerationStore(database_url)
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


def test_hard_failure_discards_staging_and_keeps_current(database_url: str):
    store = GenerationStore(database_url)
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
    with store.connection() as connection:
        staging = connection.execute(
            "SELECT COUNT(*) FROM dataset_generations WHERE status IN ('staging', 'validated')"
        ).fetchone()[0]
    assert staging == 0


def test_successful_scrape_publishes_new_current(database_url: str):
    store = GenerationStore(database_url)
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


def test_force_reclaims_active_lease_and_discards_incomplete_staging(database_url: str):
    store = GenerationStore(database_url)
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


def test_one_automatic_retry_after_collect_failure(database_url: str):
    store = GenerationStore(database_url)
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


def test_discard_staging_failure_is_surfaced_in_outcome(database_url: str, monkeypatch: pytest.MonkeyPatch):
    store = GenerationStore(database_url)
    store.migrate()
    _seed_current(store)

    def fail_publish(self, generation_id: str) -> None:
        del self, generation_id
        raise RuntimeError("publish boom")

    def fail_discard(self, generation_id: str) -> None:
        del self, generation_id
        raise RuntimeError("cannot discard")

    monkeypatch.setattr(GenerationStore, "publish", fail_publish)
    monkeypatch.setattr(GenerationStore, "discard_staging", fail_discard)

    outcome = run_scrape(
        store,
        FakeSource(
            [
                ScrapeCollection(
                    rows=sample_generation_rows(generation_suffix="b"),
                    hard_failures=(),
                    warnings=(),
                )
            ]
        ),
        holder_id="cli-1",
        max_attempts=1,
        retry_backoff_seconds=0,
    )

    assert outcome.status == "failed"
    assert "publish boom" in outcome.message
    assert "discard_staging failed: cannot discard" in outcome.message
    assert store.current_generation() == "gen-a"


def test_non_retryable_collect_errors_propagate(database_url: str):
    store = GenerationStore(database_url)
    store.migrate()
    _seed_current(store)

    class BrokenSource:
        def collect(self) -> ScrapeCollection:
            raise TypeError("programmer mistake")

    with pytest.raises(TypeError, match="programmer mistake"):
        run_scrape(store, BrokenSource(), holder_id="cli-1", retry_backoff_seconds=0)

    assert store.current_generation() == "gen-a"
    assert store.scrape_lease_holder() is None


def test_scrape_run_metadata_recorded_and_pruned(database_url: str):
    store = GenerationStore(database_url)
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
    with store.connection() as connection:
        connection.execute(
            """
            INSERT INTO scrape_runs(
                id, started_at, finished_at, outcome, generation_id,
                route_count, warning_count, error_summary
            )
            VALUES (
                'old-run', %(started)s, %(finished)s,
                'failed', NULL, 0, 0, 'ancient'
            )
            """,
            {
                "started": datetime(2000, 1, 1, tzinfo=UTC),
                "finished": datetime(2000, 1, 1, 0, 1, tzinfo=UTC),
            },
        )
        connection.commit()

    outcome = run_scrape(
        store,
        source,
        holder_id="cli-1",
        scrape_run_retention_days=30,
    )

    assert outcome.status == "published"
    with store.connection() as connection:
        rows = connection.execute(
            "SELECT id, outcome, route_count, warning_count FROM scrape_runs ORDER BY started_at"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "published"
    assert rows[0][2] == 1
    assert rows[0][3] == 1
