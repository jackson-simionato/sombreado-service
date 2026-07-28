"""Behavioral comparisons for the disposable publication PROTOTYPE."""

from __future__ import annotations

import json
import multiprocessing
import os
import queue
import signal
import sqlite3
import statistics
import time
from datetime import UTC, datetime
from hashlib import sha256
from itertools import zip_longest
from pathlib import Path
from typing import Final, TypeAlias

from .candidate import CandidateAdapter, CanonicalRows
from .models import BehaviorSnapshot, LabState, NearbySample, ScenarioResult, Verdict
from .reference import ReferenceAdapter

PUBLIC_RADII_METERS: Final = (1200.0, 2000.0)
DISTANCE_TOLERANCE_METERS: Final = 2.0
MIDPOINT_SAMPLE_COUNT: Final = 300
WORST_WORKLOAD_LOCATION: Final = (-27.58967541174793, -48.53426644737102)
_BOUNDARY_OFFSETS_METERS: Final = (-3.0, -1.0, 0.0, 1.0, 3.0)
_MINIMUM_POSITIVE_RADIUS: Final = 0.001
_MAX_RECORDED_FAILURES: Final = 20
_MISSING: Final = object()
_PUBLICATION_FAILURE_POINTS: Final = (
    "before-write",
    "during-write",
    "before-validation",
    "after-validation",
)
_PUBLICATION_SAMPLES: Final = tuple(
    NearbySample(
        lat=WORST_WORKLOAD_LOCATION[0],
        lng=WORST_WORKLOAD_LOCATION[1],
        radius_meters=radius,
    )
    for radius in PUBLIC_RADII_METERS
)
_READER_START_TIMEOUT_SECONDS: Final = 30.0
_READER_OBSERVATION_TIMEOUT_SECONDS: Final = 30.0
_PROCESS_JOIN_TIMEOUT_SECONDS: Final = 10.0
_QUEUE_POLL_SECONDS: Final = 0.1
_READER_IDLE_SECONDS: Final = 0.005
_KILLED_GENERATION_ID: Final = "generation-killed-writer"
_FIXTURE_SHA256: Final = "817aa8ee9c3ef0d6a76c9795191097a88de5129247205e1a988d94c7981dc300"
_REFERENCE_DESCRIPTION: Final = "PostgreSQL 16 / PostGIS 3.4"
_REQUIRED_SCENARIOS: Final = ("behavior", "publication", "concurrency", "durability")

ReaderRecord: TypeAlias = tuple[str, float, str, str, str]


class ScenarioLab:
    """Compare reference and candidate behavior and retain structured results."""

    def __init__(
        self,
        reference: ReferenceAdapter,
        candidate: CandidateAdapter,
        *,
        state: LabState | None = None,
        generation_a_rows: CanonicalRows | None = None,
        generation_b_rows: CanonicalRows | None = None,
        reference_a: BehaviorSnapshot | None = None,
        reference_b: BehaviorSnapshot | None = None,
    ) -> None:
        self.reference = reference
        self.candidate = candidate
        self.state = state or LabState()
        self.generation_a_rows = generation_a_rows
        self.generation_b_rows = generation_b_rows
        self.reference_a = reference_a
        self.reference_b = reference_b
        self._recorded_at: dict[str, str] = {}

    def run_all(self) -> tuple[ScenarioResult, ...]:
        """Run every required gate, retaining evidence even when one fails."""
        return (
            self.run_behavior(),
            self.run_publication(),
            self.run_concurrency(),
            self.run_durability(),
        )

    def derive_verdict(self) -> Verdict:
        """Select the next datastore experiment from the completed required gates."""
        if any(name not in self.state.results for name in _REQUIRED_SCENARIOS):
            return Verdict.pending

        required_results = tuple(self.state.results[name] for name in _REQUIRED_SCENARIOS)
        if all(result.passed for result in required_results):
            return Verdict.core_sqlite_credible
        if behavior_or_performance_failure_is_spatial_only(required_results):
            return Verdict.prototype_spatialite
        return Verdict.fallback_postgis

    def run_behavior(self) -> ScenarioResult:
        """Run the deterministic browser-visible parity corpus."""
        initial_sample = NearbySample(
            lat=WORST_WORKLOAD_LOCATION[0],
            lng=WORST_WORKLOAD_LOCATION[1],
            radius_meters=PUBLIC_RADII_METERS[-1],
        )
        initial_reference = self.reference.capture((initial_sample,))
        corpus, targeted_routes = _build_sample_corpus(initial_reference)
        evidence_samples = _boundary_evidence_samples(corpus)
        stale_route_codes = tuple(row[3] for row in initial_reference.identities)
        reference_with_evidence = self.reference.capture(
            (*corpus, *evidence_samples),
            stale_route_codes=stale_route_codes,
        )
        reference = _public_snapshot(reference_with_evidence, len(corpus))
        candidate = self.candidate.capture(
            corpus,
            stale_route_codes=stale_route_codes,
        )

        failures = _FailureRecorder()
        non_spatial_mismatches = _compare_non_spatial(
            reference,
            candidate,
            failures,
        )
        spatial = _compare_spatial(
            reference,
            candidate,
            reference_with_evidence,
            failures,
        )
        total_failures = (
            non_spatial_mismatches
            + spatial.distance_errors_over_2m
            + spatial.outside_band_differences
            + spatial.order_mismatches
        )
        identities = reference.identities
        facts = (
            ("routes", str(len({row[0] for row in identities}))),
            ("versions", str(len({row[1] for row in identities}))),
            ("directions", str(len({row[2] for row in identities}))),
            ("segments", str(len(reference.geometry))),
            ("samples", str(len(corpus))),
            ("targeted_boundary_samples", str(len(_BOUNDARY_OFFSETS_METERS) * len(PUBLIC_RADII_METERS))),
            ("targeted_boundary_routes", ",".join(targeted_routes)),
            ("non_spatial_mismatches", str(non_spatial_mismatches)),
            ("distance_comparisons", str(spatial.distance_comparisons)),
            ("distance_errors_over_2m", str(spatial.distance_errors_over_2m)),
            ("maximum_distance_error_m", f"{spatial.maximum_distance_error_m:.6f}"),
            ("boundary_band_differences", str(spatial.boundary_band_differences)),
            (
                "tolerated_boundary_details_recorded",
                str(len(spatial.tolerated_boundary_details)),
            ),
            ("outside_band_differences", str(spatial.outside_band_differences)),
            (
                "worst_2000_boundary_band_differences",
                str(len(spatial.worst_2000_boundary_details)),
            ),
            (
                "worst_2000_boundary_routes",
                ",".join(spatial.worst_2000_boundary_details),
            ),
            (
                "worst_2000_outside_band_differences",
                str(len(spatial.worst_2000_outside_details)),
            ),
            (
                "worst_2000_outside_routes",
                ",".join(spatial.worst_2000_outside_details),
            ),
            (
                "worst_2000_exact_order_match",
                str(spatial.worst_2000_exact_order_match).lower(),
            ),
            (
                "worst_2000_order_mismatches",
                str(spatial.worst_2000_order_mismatches),
            ),
            ("order_mismatches", str(spatial.order_mismatches)),
            ("uncategorized_mismatches", "0"),
            ("total_failures", str(total_failures)),
        )
        facts += tuple(
            (f"tolerated_boundary_detail.{index}", detail)
            for index, detail in enumerate(
                spatial.tolerated_boundary_details,
                start=1,
            )
        )
        result = ScenarioResult(
            name="behavior",
            passed=total_failures == 0,
            facts=facts,
            failures=tuple(failures.details),
        )
        return self._record(result)

    def run_publication(self) -> ScenarioResult:
        """Prove failures preserve A and one commit makes the complete B visible."""
        generation_a_rows, generation_b_rows, reference_a, reference_b = self._publication_inputs()
        expected_a_ids = _current_version_ids(generation_a_rows)
        expected_b_ids = _current_version_ids(generation_b_rows)
        if expected_a_ids & expected_b_ids:
            raise RuntimeError("generation A and B route-version IDs must be disjoint")

        self._reset_to_generation_a(generation_a_rows)
        candidate_a = _capture_publication_behavior(self.candidate)
        candidate_a_digest = _behavior_digest(candidate_a)

        expected_b = CandidateAdapter(self.candidate.database_path.with_name("expected-generation-b.sqlite"))
        expected_b.reset()
        _publish_generation(expected_b, "generation-b", generation_b_rows)
        candidate_b = _capture_publication_behavior(expected_b)
        candidate_b_digest = _behavior_digest(candidate_b)

        failures = _FailureRecorder()
        a_non_spatial_mismatches = _compare_non_spatial(
            reference_a,
            candidate_a,
            failures,
        )
        b_non_spatial_mismatches = _compare_non_spatial(
            reference_b,
            candidate_b,
            failures,
        )
        if candidate_a_digest == candidate_b_digest:
            failures.add("generation A and B have the same complete behavior digest")

        injected_failures = 0
        old_generation_preserved = 0
        mixed_generation_reads = 0
        for failure_point in _PUBLICATION_FAILURE_POINTS:
            self._reset_to_generation_a(generation_a_rows)
            try:
                self.candidate.stage(
                    "generation-b",
                    generation_b_rows,
                    fail_at=failure_point,
                )
            except RuntimeError as error:
                if str(error) != f"injected candidate failure: {failure_point}":
                    failures.add(f"{failure_point}: unexpected injected error: {error}")
                else:
                    injected_failures += 1
            else:
                failures.add(f"{failure_point}: staging did not raise the injected failure")

            active_generation = self.candidate.active_generation()
            observed = _capture_publication_behavior(self.candidate)
            observed_digest = _behavior_digest(observed)
            active_version_ids = set(self.candidate.active_route_version_ids())
            mixed = bool(active_version_ids & expected_a_ids) and bool(active_version_ids & expected_b_ids)
            if mixed:
                mixed_generation_reads += 1
                failures.add(f"{failure_point}: active membership mixes A and B route-version IDs")
            preserved = (
                active_generation == "generation-a"
                and active_version_ids == expected_a_ids
                and observed == candidate_a
                and observed_digest == candidate_a_digest
            )
            if preserved:
                old_generation_preserved += 1
            else:
                failures.add(
                    f"{failure_point}: generation A was not completely preserved "
                    f"active_generation={active_generation!r} "
                    f"behavior_digest={observed_digest}"
                )

        self._reset_to_generation_a(generation_a_rows)
        _publish_generation(self.candidate, "generation-b", generation_b_rows)
        published_generation = self.candidate.active_generation()
        published = _capture_publication_behavior(self.candidate)
        published_digest = _behavior_digest(published)
        published_ids = set(self.candidate.active_route_version_ids())
        published_mixed = bool(published_ids & expected_a_ids) and bool(published_ids & expected_b_ids)
        if published_mixed:
            mixed_generation_reads += 1
            failures.add("published B active membership mixes A and B route-version IDs")
        if published_generation != "generation-b":
            failures.add(f"published active generation was {published_generation!r}, expected 'generation-b'")
        if published_ids != expected_b_ids:
            failures.add("published B active membership does not equal generation B")
        if published != candidate_b or published_digest != candidate_b_digest:
            failures.add(
                "published B complete behavior did not equal the deterministic generation B snapshot "
                f"behavior_digest={published_digest}"
            )

        facts = (
            ("injected_failures", str(injected_failures)),
            ("old_generation_preserved", str(old_generation_preserved)),
            ("mixed_generation_reads", str(mixed_generation_reads)),
            ("published_generation", published_generation or "<none>"),
            ("generation_a_route_versions", str(len(expected_a_ids))),
            ("generation_b_route_versions", str(len(expected_b_ids))),
            ("generation_a_behavior_digest", candidate_a_digest),
            ("generation_b_behavior_digest", candidate_b_digest),
            ("published_behavior_digest", published_digest),
            ("generation_a_non_spatial_mismatches", str(a_non_spatial_mismatches)),
            ("generation_b_non_spatial_mismatches", str(b_non_spatial_mismatches)),
        )
        result = ScenarioResult(
            name="publication",
            passed=(
                not failures.details
                and injected_failures == len(_PUBLICATION_FAILURE_POINTS)
                and old_generation_preserved == len(_PUBLICATION_FAILURE_POINTS)
                and mixed_generation_reads == 0
                and published_generation == "generation-b"
            ),
            facts=facts,
            failures=tuple(failures.details),
        )
        self.state.active_generation = published_generation
        self.state.staging_generation = None
        return self._record(result)

    def run_concurrency(self) -> ScenarioResult:
        """Probe full-generation publication while a separate process reads snapshots."""
        generation_a_rows, generation_b_rows, _reference_a, _reference_b = self._publication_inputs()
        self._reset_to_generation_a(generation_a_rows)
        stale_route_code = self.candidate.route_search()[0][3]
        default_sample, maximum_sample = _PUBLICATION_SAMPLES
        expected_a = _reader_expectation(
            self.candidate,
            stale_route_code=stale_route_code,
            default_sample=default_sample,
            maximum_sample=maximum_sample,
        )
        expected_b_candidate = CandidateAdapter(self.candidate.database_path.with_name("expected-concurrency-b.sqlite"))
        expected_b_candidate.reset()
        _publish_generation(expected_b_candidate, "generation-b", generation_b_rows)
        expected_b = _reader_expectation(
            expected_b_candidate,
            stale_route_code=stale_route_code,
            default_sample=default_sample,
            maximum_sample=maximum_sample,
        )

        failures = _FailureRecorder()
        if expected_a[1] == expected_b[1]:
            failures.add("generation A and B reader workload digests are identical")
        if expected_a[2] == expected_b[2]:
            failures.add("generation A and B active route-version membership is identical")

        context = multiprocessing.get_context("spawn")
        stop_event = context.Event()
        reader_queue = context.Queue()
        reader = context.Process(
            target=_reader_process,
            args=(
                str(self.candidate.database_path),
                reader_queue,
                stop_event,
                stale_route_code,
                default_sample,
                maximum_sample,
            ),
            name="sqlite-publication-reader",
        )
        records: list[ReaderRecord] = []
        observed_a = False
        observed_b = False
        checkpoint_result: tuple[int, int, int] | None = None
        backup_path = self.candidate.database_path.with_name("concurrency-backup.sqlite")
        reader_started = False
        reader_exited = False
        reader_forced_termination = False
        try:
            reader.start()
            reader_started = True
            observed_a = _collect_reader_until(
                reader,
                reader_queue,
                records,
                expected_digest=expected_a[1],
                timeout_seconds=_READER_START_TIMEOUT_SECONDS,
            )
            if not observed_a:
                failures.add("reader did not observe complete generation A before publication")

            try:
                _publish_generation(self.candidate, "generation-b", generation_b_rows)
                checkpoint_result = self.candidate.checkpoint_truncate()
                self.candidate.backup_to(backup_path)
            except Exception as error:
                failures.add(f"concurrent lifecycle operation failed: {type(error).__name__}: {error}")

            observed_b = _collect_reader_until(
                reader,
                reader_queue,
                records,
                expected_digest=expected_b[1],
                timeout_seconds=_READER_OBSERVATION_TIMEOUT_SECONDS,
            )
            if not observed_b:
                failures.add("reader did not observe complete generation B after publication")
        finally:
            try:
                if reader_started:
                    reader_exited, reader_forced_termination = _stop_reader(reader, stop_event)
            finally:
                try:
                    _drain_reader_queue(reader_queue, records)
                finally:
                    reader_queue.close()
                    reader_queue.join_thread()

        reader_clean_shutdown = reader_exited and not reader_forced_termination
        if not reader_exited:
            failures.add("reader did not exit within the bounded shutdown timeout")
        if reader_forced_termination:
            failures.add("reader required forced Process.kill() termination")
        checkpoint_ok = checkpoint_result is not None and checkpoint_result[0] == 0
        if not checkpoint_ok:
            failures.add(f"TRUNCATE checkpoint reported busy: {_checkpoint_text(checkpoint_result)}")

        expected_by_generation = {
            expected_a[0]: expected_a,
            expected_b[0]: expected_b,
        }
        known_digests = {expected_a[1], expected_b[1]}
        successful_reads = 0
        busy_errors = 0
        reader_errors = 0
        unknown_digests = 0
        mixed_generation_reads = 0
        generation_a_observations = 0
        generation_b_observations = 0
        latencies = [record[1] for record in records]
        for generation, _elapsed_ms, error_text, digest, membership_digest in records:
            if error_text:
                reader_errors += 1
                if "locked" in error_text.lower() or "busy" in error_text.lower():
                    busy_errors += 1
                failures.add(f"reader error: {error_text}")
                continue
            expected = expected_by_generation.get(generation)
            if digest not in known_digests:
                unknown_digests += 1
                failures.add(f"reader observed unknown content digest {digest}")
                continue
            if expected is None or (digest, membership_digest) != (expected[1], expected[3]):
                mixed_generation_reads += 1
                failures.add(
                    "reader observed mixed generation "
                    f"generation={generation!r} digest={digest} membership_digest={membership_digest}"
                )
                continue
            successful_reads += 1
            if generation == "generation-a":
                generation_a_observations += 1
            elif generation == "generation-b":
                generation_b_observations += 1

        plans: tuple[tuple[str, ...], ...] = ()
        try:
            plans = tuple(self.candidate.nearby_query_plan(sample) for sample in _PUBLICATION_SAMPLES)
        except Exception as error:
            failures.add(f"nearby query plan inspection failed: {type(error).__name__}: {error}")
        plan_details = tuple(detail for plan in plans for detail in plan)
        plan_uses_rtree = bool(plans) and all(
            any("segment_rtree" in detail.lower() for detail in plan) for plan in plans
        )
        plan_uses_active_membership = bool(plans) and all(
            any("dataset_route_versions" in detail.lower() for detail in plan)
            and any("active_dataset" in detail.lower() for detail in plan)
            for plan in plans
        )
        if not plan_uses_rtree:
            failures.add("nearby query plan did not name segment_rtree")
        if not plan_uses_active_membership:
            failures.add("nearby query plan did not use active generation membership")

        p50_ms, p95_ms, maximum_ms = _latency_summary(latencies)
        facts = (
            ("requests", str(len(records))),
            ("successful_reads", str(successful_reads)),
            ("generation_a_observations", str(generation_a_observations)),
            ("generation_b_observations", str(generation_b_observations)),
            ("p50_ms", f"{p50_ms:.6f}"),
            ("p95_ms", f"{p95_ms:.6f}"),
            ("maximum_ms", f"{maximum_ms:.6f}"),
            ("busy_errors", str(busy_errors)),
            ("reader_errors", str(reader_errors)),
            ("unknown_digests", str(unknown_digests)),
            ("mixed_generation_reads", str(mixed_generation_reads)),
            ("reader_clean_shutdown", str(reader_clean_shutdown).lower()),
            ("reader_forced_termination", str(reader_forced_termination).lower()),
            ("generation_a_digest", expected_a[1]),
            ("generation_b_digest", expected_b[1]),
            ("checkpoint", _checkpoint_text(checkpoint_result)),
            ("online_backup_exists", str(backup_path.exists()).lower()),
            ("plan_uses_segment_rtree", str(plan_uses_rtree).lower()),
            ("plan_uses_active_membership", str(plan_uses_active_membership).lower()),
            ("plan_details", " | ".join(plan_details)),
        )
        result = ScenarioResult(
            name="concurrency",
            passed=(
                not failures.details
                and observed_a
                and observed_b
                and generation_a_observations > 0
                and generation_b_observations > 0
                and busy_errors == 0
                and mixed_generation_reads == 0
                and unknown_digests == 0
                and reader_errors == 0
                and reader_clean_shutdown
                and not reader_forced_termination
                and plan_uses_rtree
                and plan_uses_active_membership
                and checkpoint_ok
                and backup_path.exists()
            ),
            facts=facts,
            failures=tuple(failures.details),
        )
        self.state.active_generation = self.candidate.active_generation()
        return self._record(result)

    def run_durability(self) -> ScenarioResult:
        """Kill an uncommitted writer, then verify recovery and a restored backup."""
        generation_a_rows, generation_b_rows, _reference_a, _reference_b = self._publication_inputs()
        self._reset_to_generation_a(generation_a_rows)
        _publish_generation(self.candidate, "generation-b", generation_b_rows)
        baseline = _capture_publication_behavior(self.candidate)
        baseline_digest = _behavior_digest(baseline)
        marker_route_id, marker_version_id = self.candidate.route_search()[0][:2]

        failures = _FailureRecorder()
        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=False)
        writer = context.Process(
            target=_killable_writer_process,
            args=(
                str(self.candidate.database_path),
                _KILLED_GENERATION_ID,
                marker_route_id,
                marker_version_id,
                child_connection,
            ),
            name="sqlite-killable-writer",
        )
        writer_ready = False
        writer_started = False
        writer_kill_issued = False
        writer_exited = False
        try:
            writer.start()
            writer_started = True
            child_connection.close()
            if parent_connection.poll(_PROCESS_JOIN_TIMEOUT_SECONDS):
                writer_message = parent_connection.recv()
                writer_ready = writer_message == "ready"
                if not writer_ready:
                    failures.add(f"killable writer failed before ready: {writer_message}")
            else:
                failures.add("killable writer did not signal an open transaction before timeout")

            if writer_ready:
                if writer.is_alive():
                    writer.kill()
                    writer_kill_issued = True
                else:
                    failures.add("ready writer exited before the parent could issue Process.kill()")
                writer.join(_PROCESS_JOIN_TIMEOUT_SECONDS)
        finally:
            try:
                if writer_started:
                    if writer.is_alive():
                        writer.kill()
                    writer.join(_PROCESS_JOIN_TIMEOUT_SECONDS)
                    writer_exited = not writer.is_alive()
            finally:
                try:
                    parent_connection.close()
                finally:
                    child_connection.close()

        if not writer_exited:
            failures.add("killable writer did not exit within the bounded cleanup timeout")
        writer_sigkill_exit = _is_sigkill_exit(writer.exitcode)
        if writer_ready and not writer_kill_issued:
            failures.add("parent did not issue Process.kill() after the writer ready signal")
        if writer_kill_issued and not writer_sigkill_exit:
            failures.add(f"killed writer exit status was {writer.exitcode!r}, expected SIGKILL")

        killed_transaction_visible = self.candidate.has_generation(_KILLED_GENERATION_ID)
        recovered_generation = self.candidate.active_generation()
        recovered = _capture_publication_behavior(self.candidate)
        recovered_behavior_match = recovered == baseline and _behavior_digest(recovered) == baseline_digest
        if killed_transaction_visible:
            failures.add("fresh connection found the killed writer marker generation")
        if recovered_generation != "generation-b":
            failures.add(f"active generation after writer death was {recovered_generation!r}")
        if not recovered_behavior_match:
            failures.add("active behavior changed after the uncommitted writer was killed")

        integrity_rows, foreign_key_rows = self.candidate.integrity()
        integrity_ok = integrity_rows == (("ok",),)
        if not integrity_ok:
            failures.add(f"candidate integrity check failed: {integrity_rows!r}")
        if foreign_key_rows:
            failures.add(f"candidate foreign key check found rows: {foreign_key_rows!r}")

        checkpoint_result: tuple[int, int, int] | None = None
        restored_path = self.candidate.database_path.with_name("restored.sqlite")
        try:
            checkpoint_result = self.candidate.checkpoint_truncate()
            self.candidate.backup_to(restored_path)
        except Exception as error:
            failures.add(f"recovery backup operation failed: {type(error).__name__}: {error}")
        checkpoint_ok = checkpoint_result is not None and checkpoint_result[0] == 0
        if not checkpoint_ok:
            failures.add(f"TRUNCATE checkpoint reported busy: {_checkpoint_text(checkpoint_result)}")

        restored_integrity_rows: tuple[tuple[object, ...], ...] = ()
        restored_foreign_key_rows: tuple[tuple[object, ...], ...] = ()
        restored_behavior_match = False
        restored_generation: str | None = None
        if restored_path.exists():
            restored = CandidateAdapter(restored_path)
            restored_integrity_rows, restored_foreign_key_rows = restored.integrity()
            restored_generation = restored.active_generation()
            restored_behavior = _capture_publication_behavior(restored)
            restored_behavior_match = (
                restored_generation == "generation-b"
                and restored_behavior == baseline
                and _behavior_digest(restored_behavior) == baseline_digest
            )
            if restored_integrity_rows != (("ok",),):
                failures.add(f"restored integrity check failed: {restored_integrity_rows!r}")
            if restored_foreign_key_rows:
                failures.add(f"restored foreign key check found rows: {restored_foreign_key_rows!r}")
            if not restored_behavior_match:
                failures.add("restored behavior did not equal the pre-kill active behavior")
        else:
            failures.add("recovery backup did not create restored.sqlite")

        facts = (
            ("writer_ready", str(writer_ready).lower()),
            ("writer_kill_issued", str(writer_kill_issued).lower()),
            ("writer_sigkill_exit", str(writer_sigkill_exit).lower()),
            ("writer_exitcode", str(writer.exitcode)),
            ("killed_transaction_visible", str(killed_transaction_visible).lower()),
            ("recovered_generation", recovered_generation or "<none>"),
            ("recovered_behavior_match", str(recovered_behavior_match).lower()),
            ("integrity", _integrity_text(integrity_rows)),
            ("foreign_key_violations", str(len(foreign_key_rows))),
            ("checkpoint", _checkpoint_text(checkpoint_result)),
            ("restored_exists", str(restored_path.exists()).lower()),
            ("restored_generation", restored_generation or "<none>"),
            ("restored_integrity", _integrity_text(restored_integrity_rows)),
            ("restored_foreign_key_violations", str(len(restored_foreign_key_rows))),
            ("restored_behavior_match", str(restored_behavior_match).lower()),
            ("baseline_behavior_digest", baseline_digest),
        )
        result = ScenarioResult(
            name="durability",
            passed=(
                not failures.details
                and writer_ready
                and writer_kill_issued
                and writer_sigkill_exit
                and writer_exited
                and not killed_transaction_visible
                and recovered_generation == "generation-b"
                and recovered_behavior_match
                and integrity_ok
                and not foreign_key_rows
                and checkpoint_ok
                and restored_path.exists()
                and restored_integrity_rows == (("ok",),)
                and not restored_foreign_key_rows
                and restored_behavior_match
            ),
            facts=facts,
            failures=tuple(failures.details),
        )
        self.state.active_generation = recovered_generation
        return self._record(result)

    def _record(self, result: ScenarioResult) -> ScenarioResult:
        self.state.results[result.name] = result
        self._recorded_at[result.name] = datetime.now(UTC).isoformat()
        self.state.verdict = self.derive_verdict()
        self.write_evidence()
        return result

    def write_evidence(self) -> None:
        """Atomically replace the stable, inspectable evidence document."""
        if self.state.temp_dir is None:
            return

        evidence_path = self.state.temp_dir / "prototype-evidence.json"
        payload = {
            "fixture_sha256": _FIXTURE_SHA256,
            "reference": _REFERENCE_DESCRIPTION,
            "sqlite_version": sqlite3.sqlite_version,
            "updated_at_utc": datetime.now(UTC).isoformat(),
            "active_generation": self.state.active_generation,
            "staging_generation": self.state.staging_generation,
            "database_sizes_bytes": _database_sizes(self.candidate.database_path.parent),
            "query_plan_evidence": _query_plan_evidence(self.state.results),
            "results": {
                name: {
                    "passed": result.passed,
                    "facts": dict(result.facts),
                    "failures": list(result.failures),
                    "recorded_at_utc": self._recorded_at.get(name),
                }
                for name, result in self.state.results.items()
            },
            "verdict": self.state.verdict.value,
        }
        temporary_path = evidence_path.with_name(f".{evidence_path.name}.{os.getpid()}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, evidence_path)
            _fsync_directory(evidence_path.parent)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def _publication_inputs(
        self,
    ) -> tuple[CanonicalRows, CanonicalRows, BehaviorSnapshot, BehaviorSnapshot]:
        if (
            self.generation_a_rows is None
            or self.generation_b_rows is None
            or self.reference_a is None
            or self.reference_b is None
        ):
            raise RuntimeError("publication scenario requires generation A/B exports and reference snapshots")
        return (
            self.generation_a_rows,
            self.generation_b_rows,
            self.reference_a,
            self.reference_b,
        )

    def _reset_to_generation_a(self, rows: CanonicalRows) -> None:
        self.candidate.reset()
        _publish_generation(self.candidate, "generation-a", rows)


def behavior_or_performance_failure_is_spatial_only(
    required_results: tuple[ScenarioResult, ...],
) -> bool:
    """Return whether the only failed required gates are spatial limitations.

    Publication, concurrency, durability, integrity, and recovery failures
    prove that the candidate is not a safe replacement regardless of spatial
    behavior. The current lab records R*Tree query-plan evidence under the
    concurrency gate, so a failure there remains a concurrency failure.
    """
    results = {result.name: result for result in required_results}
    if set(results) != set(_REQUIRED_SCENARIOS):
        return False
    if not results["publication"].passed or not results["concurrency"].passed or not results["durability"].passed:
        return False

    behavior = results["behavior"]
    behavior_facts = dict(behavior.facts)
    if not behavior.passed:
        spatial_failures = sum(
            _fact_integer(behavior_facts, key)
            for key in (
                "distance_errors_over_2m",
                "outside_band_differences",
                "order_mismatches",
            )
        )
        if (
            _fact_integer(behavior_facts, "non_spatial_mismatches") != 0
            or _fact_integer(behavior_facts, "uncategorized_mismatches") != 0
            or spatial_failures == 0
        ):
            return False

    return any(not result.passed for result in required_results)


def _fact_integer(facts: dict[str, str], key: str) -> int:
    try:
        return int(facts.get(key, "0"))
    except ValueError:
        return -1


def _database_sizes(directory: Path) -> dict[str, int]:
    return {path.name: path.stat().st_size for path in sorted(directory.glob("*.sqlite*")) if path.is_file()}


def _query_plan_evidence(results: dict[str, ScenarioResult]) -> dict[str, str]:
    return {key: value for result in results.values() for key, value in result.facts if "plan" in key}


def _fsync_directory(directory: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _reader_process(
    database_path: str,
    reader_queue,
    stop_event,
    stale_route_code: str,
    default_sample: NearbySample,
    maximum_sample: NearbySample,
) -> None:
    """Continuously capture one read mix on a dedicated child-process connection."""
    started_at = time.monotonic()
    try:
        candidate = CandidateAdapter(Path(database_path))
        with candidate.reader_connection() as connection:
            while not stop_event.is_set():
                iteration_started_at = time.perf_counter()
                generation = "<none>"
                digest = ""
                membership_digest = ""
                error_text = ""
                try:
                    generation, membership, workload = candidate.reader_workload(
                        connection,
                        stale_route_code=stale_route_code,
                        default_radius_sample=default_sample,
                        maximum_radius_sample=maximum_sample,
                    )
                    digest = _reader_workload_digest(workload)
                    membership_digest = _membership_digest(membership)
                except Exception as error:
                    error_text = f"{type(error).__name__}: {error}"
                elapsed_ms = (time.perf_counter() - iteration_started_at) * 1000.0
                reader_queue.put((generation, elapsed_ms, error_text, digest, membership_digest))
                if stop_event.wait(_READER_IDLE_SECONDS):
                    break
    except Exception as error:
        elapsed_ms = (time.monotonic() - started_at) * 1000.0
        reader_queue.put(("<none>", elapsed_ms, f"{type(error).__name__}: {error}", "", ""))


def _killable_writer_process(
    database_path: str,
    marker_generation_id: str,
    route_id: str,
    route_version_id: str,
    ready_connection,
) -> None:
    """Leave a marker transaction uncommitted until the parent kills this process."""
    try:
        candidate = CandidateAdapter(Path(database_path))
        with candidate.reader_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO dataset_generations(id, status, created_at)
                VALUES (?, 'staging', 'writer-death-probe')
                """,
                (marker_generation_id,),
            )
            connection.execute(
                """
                INSERT INTO dataset_route_versions(generation_id, route_id, route_version_id)
                VALUES (?, ?, ?)
                """,
                (marker_generation_id, route_id, route_version_id),
            )
            ready_connection.send("ready")
            while True:
                time.sleep(1.0)
    except Exception as error:
        try:
            ready_connection.send(f"{type(error).__name__}: {error}")
        except (BrokenPipeError, OSError):  # fmt: skip
            pass
    finally:
        ready_connection.close()


def _reader_expectation(
    candidate: CandidateAdapter,
    *,
    stale_route_code: str,
    default_sample: NearbySample,
    maximum_sample: NearbySample,
) -> tuple[str, str, tuple[str, ...], str]:
    with candidate.reader_connection() as connection:
        generation, membership, workload = candidate.reader_workload(
            connection,
            stale_route_code=stale_route_code,
            default_radius_sample=default_sample,
            maximum_radius_sample=maximum_sample,
        )
    return generation, _reader_workload_digest(workload), membership, _membership_digest(membership)


def _reader_workload_digest(workload: object) -> str:
    encoded = json.dumps(
        workload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _membership_digest(membership: tuple[str, ...]) -> str:
    encoded = json.dumps(membership, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _collect_reader_until(
    reader,
    reader_queue,
    records: list[ReaderRecord],
    *,
    expected_digest: str,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            record = reader_queue.get(timeout=min(_QUEUE_POLL_SECONDS, max(0.0, deadline - time.monotonic())))
        except queue.Empty:
            if not reader.is_alive():
                break
            continue
        records.append(record)
        if record[2] == "" and record[3] == expected_digest:
            return True
    return False


def _stop_reader(reader, stop_event) -> tuple[bool, bool]:
    stop_event.set()
    reader.join(_PROCESS_JOIN_TIMEOUT_SECONDS)
    forced_termination = reader.is_alive()
    if reader.is_alive():
        reader.kill()
        reader.join(_PROCESS_JOIN_TIMEOUT_SECONDS)
    return not reader.is_alive(), forced_termination


def _is_sigkill_exit(exitcode: int | None) -> bool:
    sigkill = getattr(signal, "SIGKILL", None)
    if os.name == "posix" and sigkill is not None:
        return exitcode == -int(sigkill)
    return exitcode is not None and exitcode != 0


def _drain_reader_queue(reader_queue, records: list[ReaderRecord]) -> None:
    while True:
        try:
            records.append(reader_queue.get_nowait())
        except queue.Empty:
            return


def _latency_summary(latencies: list[float]) -> tuple[float, float, float]:
    if not latencies:
        return 0.0, 0.0, 0.0
    if len(latencies) == 1:
        return latencies[0], latencies[0], latencies[0]
    percentiles = statistics.quantiles(latencies, n=100, method="inclusive")
    return percentiles[49], percentiles[94], max(latencies)


def _checkpoint_text(checkpoint: tuple[int, int, int] | None) -> str:
    if checkpoint is None:
        return "<not-run>"
    return ",".join(str(value) for value in checkpoint)


def _integrity_text(rows: tuple[tuple[object, ...], ...]) -> str:
    if not rows:
        return "<not-run>"
    return ",".join(str(value) for value in rows[0])


class _FailureRecorder:
    def __init__(self) -> None:
        self.details: list[str] = []

    def add(self, detail: str) -> None:
        if len(self.details) < _MAX_RECORDED_FAILURES:
            self.details.append(detail)


def _publish_generation(
    candidate: CandidateAdapter,
    generation_id: str,
    rows: CanonicalRows,
) -> None:
    candidate.stage(generation_id, rows)
    candidate.validate(generation_id)
    candidate.publish(generation_id)


def _capture_publication_behavior(candidate: CandidateAdapter) -> BehaviorSnapshot:
    route_codes = tuple(row[3] for row in candidate.route_search())
    return candidate.capture(
        _PUBLICATION_SAMPLES,
        stale_route_codes=route_codes,
    )


def _current_version_ids(rows: CanonicalRows) -> set[str]:
    return {str(row["id"]) for row in rows["route_versions"] if bool(row["is_current"])}


def _behavior_digest(snapshot: BehaviorSnapshot) -> str:
    payload = {
        "identities": snapshot.identities,
        "direction_labels": snapshot.direction_labels,
        "geometry": snapshot.geometry,
        "stale_version_results": snapshot.stale_version_results,
        "nearby": tuple(
            (
                sample.lat,
                sample.lng,
                sample.radius_meters,
                rows,
            )
            for sample, rows in snapshot.nearby
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class _SpatialCounts:
    def __init__(self) -> None:
        self.distance_comparisons = 0
        self.distance_errors_over_2m = 0
        self.maximum_distance_error_m = 0.0
        self.boundary_band_differences = 0
        self.tolerated_boundary_details: list[str] = []
        self.outside_band_differences = 0
        self.worst_2000_boundary_details: list[str] = []
        self.worst_2000_outside_details: list[str] = []
        self.worst_2000_exact_order_match = False
        self.worst_2000_order_mismatches = 0
        self.order_mismatches = 0


def _build_sample_corpus(
    reference: BehaviorSnapshot,
) -> tuple[tuple[NearbySample, ...], tuple[str, ...]]:
    if len(reference.geometry) < MIDPOINT_SAMPLE_COUNT:
        raise RuntimeError(f"reference has fewer than {MIDPOINT_SAMPLE_COUNT} segments: {len(reference.geometry)}")
    midpoint_samples: list[NearbySample] = []
    for index in _evenly_spaced_indices(
        len(reference.geometry),
        MIDPOINT_SAMPLE_COUNT,
    ):
        lat, lng = _segment_midpoint(reference.geometry[index][4])
        midpoint_samples.extend(NearbySample(lat=lat, lng=lng, radius_meters=radius) for radius in PUBLIC_RADII_METERS)

    worst_samples = [
        NearbySample(
            lat=WORST_WORKLOAD_LOCATION[0],
            lng=WORST_WORKLOAD_LOCATION[1],
            radius_meters=radius,
        )
        for radius in PUBLIC_RADII_METERS
    ]
    if not reference.nearby or not reference.nearby[0][1]:
        raise RuntimeError("reference returned no routes at the measured worst point")
    worst_rows = reference.nearby[0][1]
    targeted_samples: list[NearbySample] = []
    targeted_routes: list[str] = []
    for public_radius in PUBLIC_RADII_METERS:
        route_code, route_distance = min(
            worst_rows,
            key=lambda row: (abs(row[1] - public_radius), row[0]),
        )
        targeted_routes.append(route_code)
        targeted_samples.extend(
            NearbySample(
                lat=WORST_WORKLOAD_LOCATION[0],
                lng=WORST_WORKLOAD_LOCATION[1],
                radius_meters=min(
                    max(route_distance + offset, _MINIMUM_POSITIVE_RADIUS),
                    PUBLIC_RADII_METERS[-1],
                ),
            )
            for offset in _BOUNDARY_OFFSETS_METERS
        )

    return (
        tuple((*midpoint_samples, *worst_samples, *targeted_samples)),
        tuple(targeted_routes),
    )


def _evenly_spaced_indices(total: int, count: int) -> tuple[int, ...]:
    return tuple(index * (total - 1) // (count - 1) for index in range(count))


def _segment_midpoint(geometry: str) -> tuple[float, float]:
    wkt = geometry.split(";", maxsplit=1)[-1].strip()
    start = wkt.find("(")
    end = wkt.rfind(")")
    if not wkt.upper().startswith("LINESTRING") or start < 0 or end <= start:
        raise ValueError(f"route segment has invalid LINESTRING geometry: {geometry}")
    points = wkt[start + 1 : end].split(",")
    start_lng, start_lat = (float(value) for value in points[0].strip().split())
    end_lng, end_lat = (float(value) for value in points[-1].strip().split())
    return (start_lat + end_lat) / 2.0, (start_lng + end_lng) / 2.0


def _boundary_evidence_samples(
    corpus: tuple[NearbySample, ...],
) -> tuple[NearbySample, ...]:
    locations = dict.fromkeys((sample.lat, sample.lng) for sample in corpus)
    return tuple(
        NearbySample(
            lat=lat,
            lng=lng,
            radius_meters=PUBLIC_RADII_METERS[-1] + DISTANCE_TOLERANCE_METERS,
        )
        for lat, lng in locations
    )


def _public_snapshot(
    snapshot: BehaviorSnapshot,
    sample_count: int,
) -> BehaviorSnapshot:
    public_nearby = snapshot.nearby[:sample_count]
    return BehaviorSnapshot(
        identities=snapshot.identities,
        direction_labels=snapshot.direction_labels,
        geometry=snapshot.geometry,
        stale_version_results=snapshot.stale_version_results,
        nearby=public_nearby,
    )


def _compare_non_spatial(
    reference: BehaviorSnapshot,
    candidate: BehaviorSnapshot,
    failures: _FailureRecorder,
) -> int:
    mismatches = 0
    fields = (
        ("identities", reference.identities, candidate.identities),
        ("direction_labels", reference.direction_labels, candidate.direction_labels),
        ("geometry", reference.geometry, candidate.geometry),
        (
            "stale_version_results",
            reference.stale_version_results,
            candidate.stale_version_results,
        ),
    )
    for category, reference_rows, candidate_rows in fields:
        for index, (reference_row, candidate_row) in enumerate(
            zip_longest(
                reference_rows,
                candidate_rows,
                fillvalue=_MISSING,
            )
        ):
            if reference_row == candidate_row:
                continue
            mismatches += 1
            failures.add(
                f"{category}[{index}] reference={_verbatim(reference_row)} candidate={_verbatim(candidate_row)}"
            )
    return mismatches


def _compare_spatial(
    reference: BehaviorSnapshot,
    candidate: BehaviorSnapshot,
    reference_evidence: BehaviorSnapshot,
    failures: _FailureRecorder,
) -> _SpatialCounts:
    counts = _SpatialCounts()
    reference_distances = {
        (sample.lat, sample.lng, route_code): distance
        for sample, rows in reference_evidence.nearby
        for route_code, distance in rows
    }
    route_names = {row[3]: row[4] for row in reference.identities}
    for sample_index, ((sample, reference_rows), (candidate_sample, candidate_rows)) in enumerate(
        zip(reference.nearby, candidate.nearby, strict=True)
    ):
        if candidate_sample != sample:
            raise RuntimeError(
                f"candidate sample order diverged at {sample_index}: "
                f"reference={sample!r} candidate={candidate_sample!r}"
            )
        reference_by_code = dict(reference_rows)
        candidate_by_code = dict(candidate_rows)
        shared_codes = reference_by_code.keys() & candidate_by_code.keys()
        for route_code in sorted(shared_codes):
            error = abs(reference_by_code[route_code] - candidate_by_code[route_code])
            counts.distance_comparisons += 1
            counts.maximum_distance_error_m = max(
                counts.maximum_distance_error_m,
                error,
            )
            if error > DISTANCE_TOLERANCE_METERS:
                counts.distance_errors_over_2m += 1
                failures.add(
                    f"distance sample={sample_index} route={route_code!r} "
                    f"reference={reference_by_code[route_code]:.6f} "
                    f"candidate={candidate_by_code[route_code]:.6f} "
                    f"error={error:.6f}"
                )

        differing_codes = reference_by_code.keys() ^ candidate_by_code.keys()
        for route_code in sorted(differing_codes):
            reference_distance = reference_distances.get((sample.lat, sample.lng, route_code))
            worst_2000_detail = (
                f"{route_code}:reference={_optional_distance(reference_distance)}:"
                f"reference_included={route_code in reference_by_code}:"
                f"candidate_included={route_code in candidate_by_code}"
            )
            within_boundary_band = (
                reference_distance is not None
                and abs(reference_distance - sample.radius_meters) <= DISTANCE_TOLERANCE_METERS
            )
            if within_boundary_band:
                counts.boundary_band_differences += 1
                if len(counts.tolerated_boundary_details) < _MAX_RECORDED_FAILURES:
                    counts.tolerated_boundary_details.append(
                        f"boundary sample={sample_index} route={route_code!r} "
                        f"radius={sample.radius_meters:.6f} "
                        f"reference_distance={reference_distance:.6f} "
                        f"reference_included={route_code in reference_by_code} "
                        f"candidate_included={route_code in candidate_by_code}"
                    )
                if _is_measured_worst_2000_sample(sample_index):
                    counts.worst_2000_boundary_details.append(worst_2000_detail)
                continue
            counts.outside_band_differences += 1
            if _is_measured_worst_2000_sample(sample_index):
                counts.worst_2000_outside_details.append(worst_2000_detail)
            failures.add(
                f"outside-boundary sample={sample_index} route={route_code!r} "
                f"radius={sample.radius_meters:.6f} "
                f"reference_distance={_optional_distance(reference_distance)} "
                f"reference_included={route_code in reference_by_code} "
                f"candidate_included={route_code in candidate_by_code}"
            )

        order_mismatches = _count_order_mismatches(
            sample_index,
            reference_rows,
            candidate_rows,
            route_names,
            failures,
        )
        counts.order_mismatches += order_mismatches
        if _is_measured_worst_2000_sample(sample_index):
            counts.worst_2000_exact_order_match = tuple(
                route_code for route_code, _distance in reference_rows
            ) == tuple(route_code for route_code, _distance in candidate_rows)
            counts.worst_2000_order_mismatches = order_mismatches
    return counts


def _is_measured_worst_2000_sample(sample_index: int) -> bool:
    return sample_index == MIDPOINT_SAMPLE_COUNT * len(PUBLIC_RADII_METERS) + 1


def _count_order_mismatches(
    sample_index: int,
    reference_rows: tuple[tuple[str, float], ...],
    candidate_rows: tuple[tuple[str, float], ...],
    route_names: dict[str, str],
    failures: _FailureRecorder,
) -> int:
    reference_by_code = dict(reference_rows)
    candidate_codes = [route_code for route_code, _distance in candidate_rows if route_code in reference_by_code]
    candidate_positions = {route_code: index for index, route_code in enumerate(candidate_codes)}
    tie_groups = _reference_tie_groups(reference_rows)
    group_by_code = {route_code: group_index for group_index, group in enumerate(tie_groups) for route_code in group}
    mismatches = 0
    for left_index, left_code in enumerate(candidate_codes):
        for right_code in candidate_codes[left_index + 1 :]:
            if group_by_code[left_code] <= group_by_code[right_code]:
                continue
            mismatches += 1
            failures.add(
                f"order cross-band sample={sample_index} "
                f"candidate_pair={(left_code, right_code)!r} "
                f"reference_groups={(group_by_code[left_code], group_by_code[right_code])!r}"
            )

    for group_index, group in enumerate(tie_groups):
        shared_group = [route_code for route_code in group if route_code in candidate_positions]
        if len(shared_group) < 2:
            continue
        candidate_group = tuple(sorted(shared_group, key=candidate_positions.__getitem__))
        canonical_group = tuple(
            sorted(
                shared_group,
                key=lambda code: (code, route_names.get(code, "")),
            )
        )
        if candidate_group == canonical_group:
            continue
        distances = tuple(reference_by_code[route_code] for route_code in group)
        mismatches += 1
        failures.add(
            f"order tie-group sample={sample_index} group={group_index} "
            f"reference_distances={distances!r} "
            f"candidate_order={candidate_group!r} canonical_order={canonical_group!r}"
        )
    return mismatches


def _reference_tie_groups(
    reference_rows: tuple[tuple[str, float], ...],
) -> tuple[tuple[str, ...], ...]:
    if not reference_rows:
        return ()
    groups: list[list[str]] = [[reference_rows[0][0]]]
    previous_distance = reference_rows[0][1]
    for route_code, distance in reference_rows[1:]:
        if distance - previous_distance > DISTANCE_TOLERANCE_METERS:
            groups.append([])
        groups[-1].append(route_code)
        previous_distance = distance
    return tuple(tuple(group) for group in groups)


def _verbatim(value: object) -> str:
    return "<missing>" if value is _MISSING else repr(value)


def _optional_distance(value: float | None) -> str:
    return "<beyond-evidence-radius>" if value is None else f"{value:.6f}"
