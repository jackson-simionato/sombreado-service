"""Terminal shell for the throwaway SQLite/PostGIS decision lab."""

from __future__ import annotations

import argparse

from .models import LabState

TITLE = "SQLite/PostGIS publication decision lab (PROTOTYPE)"
QUESTION = (
    "Can core SQLite preserve browser-visible route reads and atomic dataset publication at the measured workload?"
)
SCENARIOS = ("interactive", "behavior", "publication", "concurrency", "durability", "all")


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


def main() -> None:
    args = parse_args()
    state = LabState()
    if args.run != "interactive":
        raise SystemExit("prototype scenario implementation is not loaded yet")
    run_interactive(state)


if __name__ == "__main__":
    main()
