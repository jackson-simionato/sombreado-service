"""Full Consórcio scrape orchestration with production publish policy."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from time import sleep
from typing import Literal, Protocol
from uuid import uuid4

from sombreado.store.generation import CanonicalRows, GenerationStore, ScrapeLeaseHeldError

ScrapeOutcomeStatus = Literal["published", "failed", "lease_held"]

# Transient/source failures worth one automatic retry. Programming errors propagate.
_RETRYABLE_COLLECT_ERRORS = (OSError, PermissionError, RuntimeError, TimeoutError, ValueError)
_RETRYABLE_PUBLISH_ERRORS = (RuntimeError, ValueError, sqlite3.Error)


@dataclass(frozen=True)
class ScrapeCollection:
    """One catalogue collect result before stage/validate/publish."""

    rows: CanonicalRows
    hard_failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScrapeOutcome:
    status: ScrapeOutcomeStatus
    generation_id: str | None = None
    message: str = ""
    route_count: int = 0
    warning_count: int = 0


class CatalogueSource(Protocol):
    def collect(self) -> ScrapeCollection:
        """Fetch/parse the catalogue into canonical rows (or report hard failures)."""


def run_scrape(
    store: GenerationStore,
    source: CatalogueSource,
    *,
    force: bool = False,
    holder_id: str | None = None,
    max_attempts: int = 2,
    retry_backoff_seconds: float = 5.0,
    scrape_run_retention_days: int = 30,
    lease_ttl_seconds: int = 1200,
) -> ScrapeOutcome:
    """Lease, collect, validate, and publish — or discard under operating policy.

    Hard failures of still-listed routes block publish. Soft warnings may publish.
    Active lease fails fast unless ``force`` recovers incomplete staging.
    One automatic retry after a short backoff, then wait for the next run.
    """
    store.migrate()
    run_id = str(uuid4())
    started_at = datetime.now(UTC)
    holder = holder_id or f"scrape-{run_id}"

    try:
        store.claim_scrape_lease(holder, ttl_seconds=lease_ttl_seconds, force=force)
    except ScrapeLeaseHeldError as exc:
        outcome = ScrapeOutcome(status="lease_held", message=str(exc))
        _persist_run(
            store,
            run_id,
            started_at=started_at,
            outcome=outcome,
            retention_days=scrape_run_retention_days,
        )
        return outcome

    try:
        last_error = "scrape failed"
        route_count = 0
        warning_count = 0
        for attempt in range(max_attempts):
            if attempt > 0 and retry_backoff_seconds > 0:
                sleep(retry_backoff_seconds)
            try:
                collection = source.collect()
            except _RETRYABLE_COLLECT_ERRORS as exc:
                last_error = str(exc)
                continue

            route_count = len(collection.rows.get("route_versions", ()))
            warning_count = len(collection.warnings)
            if collection.hard_failures:
                last_error = f"hard failures: {', '.join(collection.hard_failures)}"
                continue

            generation_id = f"scrape-{uuid4()}"
            try:
                store.stage(generation_id, collection.rows)
                store.validate(generation_id)
                store.publish(generation_id)
            except _RETRYABLE_PUBLISH_ERRORS as exc:
                last_error = str(exc)
                if store.has_generation(generation_id):
                    try:
                        store.discard_staging(generation_id)
                    except RuntimeError:
                        pass
                continue

            outcome = ScrapeOutcome(
                status="published",
                generation_id=generation_id,
                message="published",
                route_count=route_count,
                warning_count=warning_count,
            )
            _persist_run(
                store,
                run_id,
                started_at=started_at,
                outcome=outcome,
                retention_days=scrape_run_retention_days,
            )
            return outcome

        outcome = ScrapeOutcome(
            status="failed",
            message=last_error,
            route_count=route_count,
            warning_count=warning_count,
        )
        _persist_run(
            store,
            run_id,
            started_at=started_at,
            outcome=outcome,
            retention_days=scrape_run_retention_days,
        )
        return outcome
    finally:
        store.release_scrape_lease(holder)


def _persist_run(
    store: GenerationStore,
    run_id: str,
    *,
    started_at: datetime,
    outcome: ScrapeOutcome,
    retention_days: int,
) -> None:
    store.record_scrape_run(
        run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        outcome=outcome.status,
        generation_id=outcome.generation_id,
        route_count=outcome.route_count,
        warning_count=outcome.warning_count,
        error_summary=None if outcome.status == "published" else outcome.message,
    )
    store.prune_scrape_runs(retention_days=retention_days)
