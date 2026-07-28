"""Terminal shell for the throwaway SQLite/PostGIS decision lab."""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .candidate import CandidateAdapter
from .fixture import load_snapshots
from .models import LabState
from .reference import ReferenceAdapter
from .scenarios import ScenarioLab

TITLE = "SQLite/PostGIS publication decision lab (PROTOTYPE)"
QUESTION = (
    "Can core SQLite preserve browser-visible route reads and atomic dataset publication at the measured workload?"
)
SCENARIOS = ("interactive", "behavior", "publication", "concurrency", "durability", "all")
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "docs/research/fixtures/route-snapshots-2026-07-28.jsonl.gz"
WORST_WORKLOAD_LOCATION = (-27.58967541174793, -48.53426644737102)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument(
        "--run",
        choices=SCENARIOS,
        default="interactive",
    )
    parser.add_argument("--keep-temp", action="store_true")
    return parser.parse_args()


def render(state: LabState) -> None:
    print(TITLE)
    print(QUESTION)
    print(f"state={state}")
    print("[q] quit")


def run_interactive(state: LabState) -> None:
    render(state)
    while input("> ").strip().lower() != "q":
        render(state)


def _setup_reference() -> tuple[ReferenceAdapter, int]:
    snapshots = load_snapshots(FIXTURE_PATH)
    reference = ReferenceAdapter()
    reference.reset_and_load(snapshots)
    return reference, len(snapshots)


@contextmanager
def _candidate_directory(*, keep: bool) -> Iterator[Path]:
    if keep:
        path = Path(tempfile.mkdtemp(prefix="sombreado-sqlite-prototype-"))
        yield path
        print(f"temporary_directory={path}")
        return
    with tempfile.TemporaryDirectory(prefix="sombreado-sqlite-prototype-") as directory:
        yield Path(directory)


def run_behavior(*, keep_temp: bool = False) -> bool:
    reference, fixture_count = _setup_reference()
    counts = reference.counts()
    canonical_rows = reference.export_generations()
    with _candidate_directory(keep=keep_temp) as temp_dir:
        candidate = CandidateAdapter(temp_dir / "candidate.sqlite")
        candidate.reset()
        candidate.stage("generation-a", canonical_rows)
        candidate.validate("generation-a")
        candidate.publish("generation-a")
        integrity_rows, foreign_key_rows = candidate.integrity()
        state = LabState(
            temp_dir=temp_dir,
            active_generation=candidate.active_generation(),
        )
        result = ScenarioLab(
            reference,
            candidate,
            state=state,
        ).run_behavior()

        print(f"scenario={result.name}")
        print(f"passed={str(result.passed).lower()}")
        print(f"fixture_routes={fixture_count}")
        print(f"reference_routes={counts['routes']}")
        print(f"reference_versions={counts['route_versions']}")
        print(f"reference_directions={counts['route_directions']}")
        print(f"reference_segments={counts['route_segments']}")
        print(f"active_generation={state.active_generation}")
        print(f"candidate_segments={candidate.active_segment_count()}")
        print(f"integrity={integrity_rows[0][0]}")
        print(f"foreign_key_violations={len(foreign_key_rows)}")
        print(f"worst_workload_location={WORST_WORKLOAD_LOCATION}")
        for key, value in result.facts:
            print(f"fact.{key}={value}")
        for index, failure in enumerate(result.failures, start=1):
            print(f"failure.{index}={failure}")
        return result.passed


def main() -> None:
    args = parse_args()
    state = LabState()
    if args.run == "behavior":
        passed = run_behavior(keep_temp=args.keep_temp)
        if not passed:
            raise SystemExit(1)
    elif args.run != "interactive":
        raise SystemExit("prototype scenario implementation is not loaded yet")
    else:
        run_interactive(state)


if __name__ == "__main__":
    main()
