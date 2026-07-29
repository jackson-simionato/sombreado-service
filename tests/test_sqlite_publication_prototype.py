from prototypes.sqlite_publication_PROTOTYPE.models import LabState, ScenarioResult, Verdict
from prototypes.sqlite_publication_PROTOTYPE.scenarios import ScenarioLab


def test_verdict_is_credible_when_every_required_gate_passes():
    lab = _lab_with_required_results(
        behavior=ScenarioResult(name="behavior", passed=True, facts=()),
        concurrency=ScenarioResult(name="concurrency", passed=True, facts=()),
    )

    assert lab.derive_verdict() is Verdict.core_sqlite_credible


def test_verdict_falls_back_for_spatial_behavior_failure_after_spatialite_rejection():
    lab = _lab_with_required_results(
        behavior=ScenarioResult(
            name="behavior",
            passed=False,
            facts=(
                ("non_spatial_mismatches", "0"),
                ("distance_errors_over_2m", "12"),
                ("outside_band_differences", "0"),
                ("order_mismatches", "0"),
                ("uncategorized_mismatches", "0"),
            ),
        ),
        concurrency=ScenarioResult(name="concurrency", passed=True, facts=()),
    )

    assert lab.derive_verdict() is Verdict.fallback_postgis


def test_verdict_falls_back_for_a_busy_reader():
    lab = _lab_with_required_results(
        behavior=ScenarioResult(name="behavior", passed=True, facts=()),
        concurrency=ScenarioResult(
            name="concurrency",
            passed=False,
            facts=(
                ("busy_errors", "1"),
                ("reader_errors", "1"),
            ),
            failures=("reader error: database is locked",),
        ),
    )

    assert lab.derive_verdict() is Verdict.fallback_postgis


def _lab_with_required_results(
    *,
    behavior: ScenarioResult,
    concurrency: ScenarioResult,
) -> ScenarioLab:
    return ScenarioLab(
        reference=None,
        candidate=None,
        state=LabState(
            results={
                "behavior": behavior,
                "publication": ScenarioResult(name="publication", passed=True, facts=()),
                "concurrency": concurrency,
                "durability": ScenarioResult(name="durability", passed=True, facts=()),
            }
        ),
    )
