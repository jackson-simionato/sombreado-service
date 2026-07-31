"""Terminal shell for the PostGIS Generation Store decision lab (PROTOTYPE)."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .fixture import NEARBY_PROBE
from .models import LabState, Verdict
from .scenarios import PUBLIC_RADIUS_METERS, ScenarioLab
from .store import PROTOTYPE_DATABASE, PostGISGenerationStore

TITLE = "PostGIS Generation Store publication + nearby lab (PROTOTYPE)"
QUESTION = (
    "Can local PostGIS demonstrate Generation Store semantics "
    "(stage → validate → atomic current flip; scrape lease; current+previous retention) "
    "plus geography ST_DWithin nearby — enough HITL confidence to lock Neon?"
)
SCENARIOS = ("interactive", "publication", "lease", "retention", "nearby", "all")
_ACTION_SCENARIOS = {
    "p": "publication",
    "l": "lease",
    "t": "retention",
    "n": "nearby",
    "a": "all",
}
_DISPLAY = ("publication", "lease", "retention", "nearby")
EVIDENCE_NAME = "prototype-evidence.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--run", choices=SCENARIOS, default="interactive")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
        help="Directory for prototype-evidence.json (default: temp dir)",
    )
    return parser.parse_args()


def render(state: LabState, message: str = "") -> None:
    print("\033[2J\033[H", end="")
    print(f"\x1b[1m{TITLE}\x1b[0m")
    print(QUESTION)
    print()
    print(f"\x1b[1mdatabase\x1b[0m={state.database or PROTOTYPE_DATABASE}")
    print(f"\x1b[1mspatial_model\x1b[0m={state.spatial_model}")
    print(f"\x1b[1mcurrent\x1b[0m={state.current_generation or '<none>'}")
    print(f"\x1b[1mprevious\x1b[0m={state.previous_generation or '<none>'}")
    print(f"\x1b[1mlease\x1b[0m={state.lease_holder or '<none>'}")
    if state.last_nearby:
        compact = ", ".join(f"{hit.route_code}:{hit.distance_meters:.2f}m" for hit in state.last_nearby)
        print(f"\x1b[1mnearby\x1b[0m={compact}")
    else:
        print("\x1b[1mnearby\x1b[0m=<none>")
    print()
    print("scenario      status   facts / failures")
    print("------------  -------  ------------------------------------------------------------")
    for name in _DISPLAY:
        result = state.results.get(name)
        if result is None:
            print(f"{name:<12}  pending  <not run>")
            continue
        status = "PASS" if result.passed else "FAIL"
        compact = ", ".join(f"{key}={value}" for key, value in result.facts[:3])
        if result.failures:
            compact = f"{compact}; failure={result.failures[0]}"
        print(f"{name:<12}  {status:<7}  {compact[:116]}")
    print()
    print(f"\x1b[1mprovisional_verdict\x1b[0m={state.verdict.value}")
    if state.evidence_path is not None:
        print(f"\x1b[2mevidence={state.evidence_path}\x1b[0m")
    if message:
        print(f"message={message}")
    print()
    print(
        "\x1b[1m[p]\x1b[0m publication  \x1b[1m[l]\x1b[0m lease  \x1b[1m[t]\x1b[0m retention  \x1b[1m[n]\x1b[0m nearby"
    )
    print("\x1b[1m[a]\x1b[0m all          \x1b[1m[r]\x1b[0m reset  \x1b[1m[q]\x1b[0m quit")


def _make_lab(evidence_dir: Path) -> tuple[ScenarioLab, LabState]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    state = LabState(
        database=PROTOTYPE_DATABASE,
        evidence_path=evidence_dir / EVIDENCE_NAME,
        spatial_model="geography(LINESTRING,4326) + ST_DWithin + GIST",
    )
    store = PostGISGenerationStore()
    lab = ScenarioLab(store, state)
    return lab, state


def run_interactive(*, evidence_dir: Path | None) -> int:
    with _evidence_directory(evidence_dir) as directory:
        lab, state = _make_lab(directory)
        message = (
            f"Probe {NEARBY_PROBE} @ {PUBLIC_RADIUS_METERS:.0f}m. "
            "Select a scenario to recreate the disposable PostGIS database."
        )
        while True:
            render(state, message)
            action = input("> ").strip().lower()
            if action == "q":
                return 0 if state.verdict != Verdict.needs_more_spike else 1
            if action == "r":
                try:
                    lab.reset()
                    message = "reset complete — disposable database recreated"
                except Exception as error:  # noqa: BLE001 — surface lab errors
                    message = f"reset refused: {type(error).__name__}: {error}"
                continue
            scenario = _ACTION_SCENARIOS.get(action)
            if scenario is None:
                message = f"unknown action: {action!r}"
                continue
            try:
                message = _run_scenario(lab, scenario)
            except Exception as error:  # noqa: BLE001 — surface lab errors
                message = f"{scenario} crashed: {type(error).__name__}: {error}"


def run_batch(scenario: str, *, evidence_dir: Path | None) -> int:
    with _evidence_directory(evidence_dir) as directory:
        lab, state = _make_lab(directory)
        message = _run_scenario(lab, scenario)
        render(state, message)
        print()
        print(f"evidence written to {state.evidence_path}")
        if state.verdict == Verdict.postgis_generation_store_credible:
            return 0
        if scenario != "all" and state.results.get(scenario, None) and state.results[scenario].passed:
            return 0
        return 1


def _run_scenario(lab: ScenarioLab, scenario: str) -> str:
    runners = {
        "publication": lab.run_publication,
        "lease": lab.run_lease,
        "retention": lab.run_retention,
        "nearby": lab.run_nearby,
    }
    if scenario == "all":
        results = lab.run_all()
        failed = [result.name for result in results if not result.passed]
        if failed:
            return f"all complete — failed: {', '.join(failed)}; verdict={lab.state.verdict.value}"
        return f"all complete — verdict={lab.state.verdict.value}"
    result = runners[scenario]()
    status = "PASS" if result.passed else "FAIL"
    detail = result.failures[0] if result.failures else "ok"
    return f"{scenario} {status}: {detail}"


class _evidence_directory:
    def __init__(self, evidence_dir: Path | None) -> None:
        self._requested = evidence_dir
        self._temp: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        if self._requested is not None:
            self.path = self._requested
            return self.path
        self._temp = tempfile.TemporaryDirectory(prefix="sombreado-postgis-prototype-")
        self.path = Path(self._temp.name)
        return self.path

    def __exit__(self, *args: object) -> None:
        if self._temp is not None:
            self._temp.cleanup()


def main() -> int:
    args = parse_args()
    if args.run == "interactive":
        return run_interactive(evidence_dir=args.evidence_dir)
    return run_batch(args.run, evidence_dir=args.evidence_dir)


if __name__ == "__main__":
    sys.exit(main())
