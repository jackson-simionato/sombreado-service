"""Behavioral comparisons for the disposable publication PROTOTYPE."""

from __future__ import annotations

import json
from hashlib import sha256
from itertools import zip_longest
from typing import Final

from .candidate import CandidateAdapter, CanonicalRows
from .models import BehaviorSnapshot, LabState, NearbySample, ScenarioResult
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
        self.state.results["behavior"] = result
        return result

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
        self.state.results["publication"] = result
        return result

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
