"""Terminal shell for the throwaway SQLite/PostGIS decision lab."""

from __future__ import annotations

import argparse
from pathlib import Path

from .fixture import load_snapshots
from .models import LabState
from .reference import ReferenceAdapter

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


def run_reference_smoke() -> None:
    reference, fixture_count = _setup_reference()
    counts = reference.counts()
    print(f"fixture_routes={fixture_count}")
    print(f"reference_routes={counts['routes']}")
    print(f"reference_versions={counts['route_versions']}")
    print(f"reference_directions={counts['route_directions']}")
    print(f"reference_segments={counts['route_segments']}")
    print(f"worst_workload_location={WORST_WORKLOAD_LOCATION}")


def main() -> None:
    args = parse_args()
    state = LabState()
    if args.run == "behavior":
        run_reference_smoke()
    elif args.run != "interactive":
        raise SystemExit("prototype scenario implementation is not loaded yet")
    else:
        run_interactive(state)


if __name__ == "__main__":
    main()
