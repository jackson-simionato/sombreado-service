"""Scenario gates for the PostGIS Generation Store PROTOTYPE."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .fixture import (
    NEARBY_PROBE,
    empty_generation,
    generation_a,
    generation_b,
    generation_c,
)
from .models import LabState, ScenarioResult, Verdict
from .store import PostGISGenerationStore, ScrapeLeaseHeldError

_REQUIRED = ("publication", "lease", "retention", "nearby")
PUBLIC_RADIUS_METERS = 1200.0


class ScenarioLab:
    """Exercise Generation Store semantics and PostGIS-only nearby."""

    def __init__(self, store: PostGISGenerationStore, state: LabState) -> None:
        self.store = store
        self.state = state

    def reset(self) -> None:
        """Recreate the disposable database and clear lab results."""
        self.store.ensure_ready()
        self.state.results.clear()
        self.state.last_nearby = ()
        self.state.verdict = Verdict.pending
        self._sync_state()
        self.write_evidence()

    def run_all(self) -> tuple[ScenarioResult, ...]:
        return (
            self.run_publication(),
            self.run_lease(),
            self.run_retention(),
            self.run_nearby(),
        )

    def derive_verdict(self) -> Verdict:
        if any(name not in self.state.results for name in _REQUIRED):
            return Verdict.pending
        if all(self.state.results[name].passed for name in _REQUIRED):
            return Verdict.postgis_generation_store_credible
        return Verdict.needs_more_spike

    def run_publication(self) -> ScenarioResult:
        """staging → validate → atomic current flip; reject incomplete publish."""
        self.store.ensure_ready()
        failures: list[str] = []

        self.store.stage(generation_a())
        if self.store.current_generation() is not None:
            failures.append("stage mutated current pointer")

        self.store.validate("gen-a")
        if self.store.current_generation() is not None:
            failures.append("validate mutated current pointer")

        self.store.publish("gen-a")
        if self.store.current_generation() != "gen-a":
            failures.append(f"publish current={self.store.current_generation()!r} want gen-a")
        if self.store.previous_generation() is not None:
            failures.append("first publish should leave previous empty")

        self.store.stage(generation_b())
        try:
            self.store.publish("gen-b")
            failures.append("unvalidated generation published")
        except RuntimeError as error:
            if "not validated" not in str(error):
                failures.append(f"unexpected publish error: {error}")
        if self.store.current_generation() != "gen-a":
            failures.append("failed publish mutated current")

        self.store.stage(empty_generation("gen-empty"))
        try:
            self.store.validate("gen-empty")
            failures.append("empty generation validated")
        except RuntimeError as error:
            if "no routes" not in str(error):
                failures.append(f"unexpected validate error: {error}")
        if self.store.has_generation("gen-empty"):
            failures.append("failed validation left staging behind")
        if self.store.current_generation() != "gen-a":
            failures.append("validate failure mutated current")

        self._sync_state()
        result = ScenarioResult(
            name="publication",
            passed=not failures,
            facts=(
                ("current", str(self.store.current_generation())),
                ("previous", str(self.store.previous_generation())),
                ("has_gen_a", str(self.store.has_generation("gen-a"))),
                ("has_gen_empty", str(self.store.has_generation("gen-empty"))),
            ),
            failures=tuple(failures),
        )
        return self._record(result)

    def run_lease(self) -> ScenarioResult:
        """Singleton scrape lease exclusion + expired reclaim."""
        self.store.ensure_ready()
        failures: list[str] = []

        self.store.claim_scrape_lease("holder-a", ttl_seconds=1200)
        if self.store.scrape_lease_holder() != "holder-a":
            failures.append("holder-a did not claim lease")

        try:
            self.store.claim_scrape_lease("holder-b", ttl_seconds=1200)
            failures.append("holder-b stole active lease")
        except ScrapeLeaseHeldError:
            pass

        self.store.stage(generation_a())
        self.store.expire_scrape_lease_for_lab()
        self.store.claim_scrape_lease("holder-b", ttl_seconds=1200)
        if self.store.scrape_lease_holder() != "holder-b":
            failures.append("expired lease was not reclaimed by holder-b")
        if self.store.has_generation("gen-a"):
            failures.append("expired reclaim left orphan staging")

        self.store.release_scrape_lease("holder-b")
        if self.store.scrape_lease_holder() is not None:
            failures.append("release left lease held")

        self.store.claim_scrape_lease("holder-c", ttl_seconds=1200)
        self.store.claim_scrape_lease("holder-d", ttl_seconds=1200, force=True)
        if self.store.scrape_lease_holder() != "holder-d":
            failures.append("force reclaim failed")

        self._sync_state()
        result = ScenarioResult(
            name="lease",
            passed=not failures,
            facts=(
                ("lease_holder", str(self.store.scrape_lease_holder())),
                ("orphan_staging_after_reclaim", str(self.store.has_generation("gen-a"))),
            ),
            failures=tuple(failures),
        )
        return self._record(result)

    def run_retention(self) -> ScenarioResult:
        """current + previous retention; drop former previous on third publish."""
        self.store.ensure_ready()
        failures: list[str] = []

        for fixture in (generation_a(), generation_b(), generation_c()):
            self.store.stage(fixture)
            self.store.validate(fixture.generation_id)
            self.store.publish(fixture.generation_id)

        if self.store.current_generation() != "gen-c":
            failures.append(f"current={self.store.current_generation()!r} want gen-c")
        if self.store.previous_generation() != "gen-b":
            failures.append(f"previous={self.store.previous_generation()!r} want gen-b")
        if self.store.has_generation("gen-a"):
            failures.append("former previous gen-a was retained")
        if not self.store.has_generation("gen-b"):
            failures.append("previous gen-b was dropped early")
        if not self.store.has_generation("gen-c"):
            failures.append("current gen-c missing")

        self._sync_state()
        result = ScenarioResult(
            name="retention",
            passed=not failures,
            facts=(
                ("current", str(self.store.current_generation())),
                ("previous", str(self.store.previous_generation())),
                ("has_gen_a", str(self.store.has_generation("gen-a"))),
                ("has_gen_b", str(self.store.has_generation("gen-b"))),
                ("has_gen_c", str(self.store.has_generation("gen-c"))),
            ),
            failures=tuple(failures),
        )
        return self._record(result)

    def run_nearby(self) -> ScenarioResult:
        """PostGIS geography ST_DWithin only sees current; radius excludes far route."""
        self.store.ensure_ready()
        failures: list[str] = []
        lat, lng = NEARBY_PROBE

        before = self.store.find_nearby(lat=lat, lng=lng, radius_meters=PUBLIC_RADIUS_METERS)
        if before:
            failures.append("nearby returned rows with no current generation")

        self.store.stage(generation_a())
        self.store.validate("gen-a")
        staged_nearby = self.store.find_nearby(lat=lat, lng=lng, radius_meters=PUBLIC_RADIUS_METERS)
        if staged_nearby:
            failures.append("nearby leaked staging generation before publish")

        self.store.publish("gen-a")
        hits = self.store.find_nearby(lat=lat, lng=lng, radius_meters=PUBLIC_RADIUS_METERS)
        codes = tuple(hit.route_code for hit in hits)
        if codes != ("1A",):
            failures.append(f"nearby codes={codes!r} want ('1A',) — far route should be excluded")
        if hits and hits[0].distance_meters > 5.0:
            failures.append(f"nearby distance {hits[0].distance_meters} m unexpectedly large")

        # Explain evidence: GIST index present for geography.
        with self.store.connection() as connection:
            plan = connection.execute(
                """
                EXPLAIN
                SELECT segment.route_code
                FROM dataset_pointers AS pointer
                JOIN route_segments AS segment
                    ON segment.generation_id = pointer.generation_id
                WHERE pointer.role = 'current'
                  AND ST_DWithin(
                      segment.geom,
                      ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography,
                      %(radius)s
                  )
                """,
                {"lat": lat, "lng": lng, "radius": PUBLIC_RADIUS_METERS},
            ).fetchall()
        plan_text = " | ".join(str(next(iter(row.values()))) for row in plan)
        uses_gist = "gist" in plan_text.lower() or "route_segments_geom_gix" in plan_text.lower()

        self.store.stage(generation_b())
        self.store.validate("gen-b")
        self.store.publish("gen-b")
        after = self.store.find_nearby(lat=lat, lng=lng, radius_meters=PUBLIC_RADIUS_METERS)
        after_codes = tuple(hit.route_code for hit in after)
        if after_codes != ("1B",):
            failures.append(f"after flip nearby codes={after_codes!r} want ('1B',)")

        self.state.last_nearby = after
        self._sync_state()
        result = ScenarioResult(
            name="nearby",
            passed=not failures,
            facts=(
                ("spatial_model", self.store.spatial_model),
                ("radius_meters", str(PUBLIC_RADIUS_METERS)),
                ("gen_a_codes", ",".join(codes)),
                ("gen_b_codes", ",".join(after_codes)),
                ("gen_a_distance_m", "none" if not hits else f"{hits[0].distance_meters:.3f}"),
                ("plan_uses_gist", str(uses_gist)),
                ("plan", plan_text[:160]),
            ),
            failures=tuple(failures),
        )
        return self._record(result)

    def write_evidence(self) -> Path:
        path = self.state.evidence_path
        if path is None:
            raise RuntimeError("evidence path not configured")
        payload = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "question": (
                "Can a cheap Postgres/PostGIS spike demonstrate reusable Generation Store "
                "semantics plus PostGIS-only nearby enough to lock Neon store design?"
            ),
            "database": self.store.database,
            "spatial_model": self.store.spatial_model,
            # Per-gate facts are authoritative: each scenario recreates the disposable DB.
            "postgis_version": self.store.snapshot().get("postgis_version"),
            "results": {
                name: {
                    "passed": result.passed,
                    "facts": dict(result.facts),
                    "failures": list(result.failures),
                }
                for name, result in self.state.results.items()
            },
            "verdict": self.state.verdict.value,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path

    def _record(self, result: ScenarioResult) -> ScenarioResult:
        self.state.results[result.name] = result
        self.state.verdict = self.derive_verdict()
        self.write_evidence()
        return result

    def _sync_state(self) -> None:
        self.state.database = self.store.database
        self.state.current_generation = self.store.current_generation()
        self.state.previous_generation = self.store.previous_generation()
        self.state.lease_holder = self.store.scrape_lease_holder()
        self.state.spatial_model = self.store.spatial_model
