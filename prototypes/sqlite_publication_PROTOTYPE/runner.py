"""Terminal shell for the throwaway SQLite/PostGIS decision lab."""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from consorcio_fenix_scraper.db import make_session_factory, persist_snapshots
from sqlalchemy import create_engine, text

from .candidate import CandidateAdapter
from .fixture import load_snapshots
from .models import LabState, NearbySample, ScenarioResult, Verdict
from .reference import REFERENCE_DATABASE, REFERENCE_URL, SOURCE_URL, ReferenceAdapter
from .scenarios import PUBLIC_RADII_METERS, ScenarioLab

TITLE = "SQLite/PostGIS publication decision lab (PROTOTYPE)"
QUESTION = (
    "Can core SQLite preserve browser-visible route reads and atomic dataset publication at the measured workload?"
)
SCENARIOS = ("interactive", "behavior", "publication", "concurrency", "durability", "all")
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "docs/research/fixtures/route-snapshots-2026-07-28.jsonl.gz"
TEMPORARY_DIRECTORY_PREFIX = "sombreado-sqlite-prototype-"
WORST_WORKLOAD_LOCATION = (-27.58967541174793, -48.53426644737102)
_ACTION_SCENARIOS = {
    "b": "behavior",
    "p": "publication",
    "c": "concurrency",
    "d": "durability",
    "a": "all",
}
_DISPLAY_SCENARIOS = ("behavior", "publication", "concurrency", "durability")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument(
        "--run",
        choices=SCENARIOS,
        default="interactive",
    )
    parser.add_argument("--keep-temp", action="store_true")
    return parser.parse_args()


def render(state: LabState, message: str = "") -> None:
    """Clear and redraw the complete interactive lab screen."""
    print("\033[2J\033[H", end="")
    print(TITLE)
    print(QUESTION)
    print(f"temporary_directory={state.temp_dir or '<not-created>'}")
    print(f"active_generation={state.active_generation or '<none>'}")
    print(f"staging_generation={state.staging_generation or '<none>'}")
    print()
    print("scenario      status   facts / failures")
    print("------------  -------  ------------------------------------------------------------")
    for name in _DISPLAY_SCENARIOS:
        result = state.results.get(name)
        if result is None:
            print(f"{name:<12}  pending  <not run>")
            continue
        status = "PASS" if result.passed else "FAIL"
        compact_facts = ", ".join(f"{key}={value}" for key, value in result.facts[:3])
        if result.failures:
            compact_facts = f"{compact_facts}; failure={result.failures[0]}"
        print(f"{name:<12}  {status:<7}  {compact_facts[:116]}")
    print()
    print(f"provisional_verdict={state.verdict.value}")
    if message:
        print(f"message={message}")
    print("[b] behavior  [p] publication  [c] concurrency  [d] durability")
    print("[a] all       [r] reset        [q] quit")


def run_interactive(*, keep_temp: bool = False) -> None:
    with _candidate_directory(keep=keep_temp) as temp_dir:
        state = LabState(temp_dir=temp_dir)
        lab: ScenarioLab | None = None
        message = "Select a scenario to initialize the disposable lab."
        while True:
            render(state, message)
            action = input("> ").strip().lower()
            if action == "q":
                return
            if action == "r":
                try:
                    _validate_reset_target(temp_dir)
                    state.results.clear()
                    state.active_generation = None
                    state.staging_generation = None
                    state.verdict = Verdict.pending
                    lab, _fixture_count, _counts = _setup_lab(state, publication_inputs=True)
                    lab.write_evidence()
                    message = "reset complete"
                except Exception as error:
                    message = f"reset refused: {type(error).__name__}: {error}"
                continue
            scenario = _ACTION_SCENARIOS.get(action)
            if scenario is None:
                message = f"unknown action: {action!r}"
                continue
            try:
                if lab is None:
                    lab, _fixture_count, _counts = _setup_lab(state, publication_inputs=True)
                results = _run_scenario(lab, scenario)
                message = _summary_message(results, state)
            except Exception as error:
                message = f"{scenario} error: {type(error).__name__}: {error}"


def _setup_reference() -> tuple[ReferenceAdapter, tuple[object, ...]]:
    snapshots = tuple(load_snapshots(FIXTURE_PATH))
    reference = ReferenceAdapter()
    reference.reset_and_load(snapshots)
    return reference, snapshots


def _setup_lab(
    state: LabState,
    *,
    publication_inputs: bool,
) -> tuple[ScenarioLab, int, dict[str, int]]:
    """Build one disposable reference/candidate pair for one terminal session."""
    if state.temp_dir is None:
        raise RuntimeError("a temporary lab directory is required")
    reference, snapshots = _setup_reference()
    counts = reference.counts()
    generation_a_rows = reference.export_generations()

    generation_b_rows = None
    reference_a = None
    reference_b = None
    if publication_inputs:
        reference_a = _capture_reference_publication_behavior(reference)
        _persist_generation_b(snapshots)
        generation_b_rows = reference.export_generations()
        reference_b = _capture_reference_publication_behavior(reference)

    candidate = CandidateAdapter(state.temp_dir / "candidate.sqlite")
    candidate.reset()
    initial_generation = "generation-b" if publication_inputs else "generation-a"
    initial_rows = generation_b_rows if publication_inputs else generation_a_rows
    if initial_rows is None:
        raise RuntimeError("publication inputs did not provide generation B rows")
    candidate.stage(initial_generation, initial_rows)
    candidate.validate(initial_generation)
    candidate.publish(initial_generation)
    state.active_generation = candidate.active_generation()
    state.staging_generation = None

    return (
        ScenarioLab(
            reference,
            candidate,
            state=state,
            generation_a_rows=generation_a_rows if publication_inputs else None,
            generation_b_rows=generation_b_rows,
            reference_a=reference_a,
            reference_b=reference_b,
        ),
        len(snapshots),
        counts,
    )


@contextmanager
def _candidate_directory(*, keep: bool) -> Iterator[Path]:
    if keep:
        path = Path(tempfile.mkdtemp(prefix=TEMPORARY_DIRECTORY_PREFIX))
        try:
            yield path
        finally:
            print(f"temporary_directory={path}")
        return
    with tempfile.TemporaryDirectory(prefix=TEMPORARY_DIRECTORY_PREFIX) as directory:
        yield Path(directory)


def _capture_reference_publication_behavior(reference: ReferenceAdapter):
    samples = tuple(
        NearbySample(
            lat=WORST_WORKLOAD_LOCATION[0],
            lng=WORST_WORKLOAD_LOCATION[1],
            radius_meters=radius,
        )
        for radius in PUBLIC_RADII_METERS
    )
    initial = reference.capture(samples)
    return reference.capture(
        samples,
        stale_route_codes=tuple(row[3] for row in initial.identities),
    )


def _persist_generation_b(snapshots: tuple[object, ...]) -> None:
    """Persist a deterministic, distinct version of every fixture snapshot."""
    generation_b = tuple(
        snapshot.model_copy(update={"source_hash": f"prototype-b:{snapshot.source_hash}"}) for snapshot in snapshots
    )
    if not all(snapshot.source_hash.startswith("prototype-b:") for snapshot in generation_b):
        raise RuntimeError("generation B source hashes do not use the required prototype-b: prefix")

    # The production scraper stores regular SHA-256 hashes in VARCHAR(64). This
    # disposable reference deliberately uses the required prefixed marker.
    engine = create_engine(REFERENCE_URL, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE route_versions ALTER COLUMN source_hash TYPE TEXT"))
    finally:
        engine.dispose()

    session_factory = make_session_factory(REFERENCE_URL)
    try:
        persist_snapshots(session_factory, SOURCE_URL, generation_b)
    finally:
        session_factory.kw["bind"].dispose()


def _run_scenario(lab: ScenarioLab, scenario: str) -> tuple[ScenarioResult, ...]:
    if scenario == "all":
        return lab.run_all()
    return (getattr(lab, f"run_{scenario}")(),)


def _run_non_interactive(scenario: str, *, keep_temp: bool) -> bool:
    with _candidate_directory(keep=keep_temp) as temp_dir:
        state = LabState(temp_dir=temp_dir)
        lab, fixture_count, counts = _setup_lab(
            state,
            publication_inputs=scenario != "behavior",
        )
        results = _run_scenario(lab, scenario)
        _print_results(results, state, fixture_count, counts, lab.candidate)
        return all(result.passed for result in results)


def _print_results(
    results: tuple[ScenarioResult, ...],
    state: LabState,
    fixture_count: int,
    counts: dict[str, int],
    candidate: CandidateAdapter,
) -> None:
    print(f"fixture_routes={fixture_count}")
    print(f"reference_routes={counts['routes']}")
    print(f"reference_versions={counts['route_versions']}")
    print(f"reference_directions={counts['route_directions']}")
    print(f"reference_segments={counts['route_segments']}")
    print(f"active_generation={state.active_generation}")
    print(f"candidate_segments={candidate.active_segment_count()}")
    print(f"worst_workload_location={WORST_WORKLOAD_LOCATION}")
    for result in results:
        print(f"scenario={result.name}")
        print(f"passed={str(result.passed).lower()}")
        for key, value in result.facts:
            print(f"fact.{key}={value}")
        for index, failure in enumerate(result.failures, start=1):
            print(f"failure.{index}={failure}")
    evidence_path = state.temp_dir / "prototype-evidence.json" if state.temp_dir else None
    print(f"provisional_verdict={state.verdict.value}")
    print(f"evidence_path={evidence_path if evidence_path and evidence_path.exists() else '<none>'}")


def _summary_message(results: tuple[ScenarioResult, ...], state: LabState) -> str:
    statuses = ", ".join(f"{result.name}={'PASS' if result.passed else 'FAIL'}" for result in results)
    return f"{statuses}; verdict={state.verdict.value}"


def _validate_reset_target(temp_dir: Path) -> None:
    """Refuse interactive resets outside the one database and temporary scope."""
    if REFERENCE_DATABASE != "sombreado_sqlite_verification":
        raise RuntimeError("refusing reset outside the fixed PostgreSQL verification database")
    resolved_temp_dir = temp_dir.resolve()
    if not resolved_temp_dir.name.startswith(TEMPORARY_DIRECTORY_PREFIX):
        raise RuntimeError("refusing reset outside the exact prototype temporary-directory prefix")
    if resolved_temp_dir.parent != Path(tempfile.gettempdir()).resolve():
        raise RuntimeError("refusing reset outside the system temporary directory")


def main() -> None:
    args = parse_args()
    if args.run == "interactive":
        run_interactive(keep_temp=args.keep_temp)
        return
    passed = _run_non_interactive(args.run, keep_temp=args.keep_temp)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
