from prototypes.sqlite_publication_PROTOTYPE.models import LabState, ScenarioResult, Verdict
from prototypes.sqlite_publication_PROTOTYPE.scenarios import ScenarioLab


def test_verdict_revised_app_distance_for_an_isolated_spatial_index_plan_failure():
    lab = _lab_with_required_results(
        concurrency=ScenarioResult(
            name="concurrency",
            passed=False,
            facts=(
                ("busy_errors", "0"),
                ("reader_errors", "0"),
                ("unknown_digests", "0"),
                ("mixed_generation_reads", "0"),
                ("generation_a_observations", "1"),
                ("generation_b_observations", "1"),
                ("reader_clean_shutdown", "true"),
                ("reader_forced_termination", "false"),
                ("checkpoint", "0,0,0"),
                ("online_backup_exists", "true"),
                ("plan_uses_spatial_index", "false"),
                ("plan_uses_active_membership", "true"),
            ),
            failures=("nearby query plan did not use SpatiaLite SpatialIndex",),
        )
    )

    assert lab.derive_verdict() is Verdict.revised_app_distance


def test_verdict_falls_back_for_a_busy_reader_even_when_the_spatial_index_plan_is_missing():
    lab = _lab_with_required_results(
        concurrency=ScenarioResult(
            name="concurrency",
            passed=False,
            facts=(
                ("busy_errors", "1"),
                ("reader_errors", "1"),
                ("unknown_digests", "0"),
                ("mixed_generation_reads", "0"),
                ("generation_a_observations", "1"),
                ("generation_b_observations", "1"),
                ("reader_clean_shutdown", "true"),
                ("reader_forced_termination", "false"),
                ("checkpoint", "0,0,0"),
                ("online_backup_exists", "true"),
                ("plan_uses_spatial_index", "false"),
                ("plan_uses_active_membership", "true"),
            ),
            failures=(
                "reader error: database is locked",
                "nearby query plan did not use SpatiaLite SpatialIndex",
            ),
        )
    )

    assert lab.derive_verdict() is Verdict.fallback_postgis


def _lab_with_required_results(*, concurrency: ScenarioResult) -> ScenarioLab:
    return ScenarioLab(
        reference=None,
        candidate=None,
        state=LabState(
            results={
                "behavior": ScenarioResult(name="behavior", passed=True, facts=()),
                "publication": ScenarioResult(name="publication", passed=True, facts=()),
                "concurrency": concurrency,
                "durability": ScenarioResult(name="durability", passed=True, facts=()),
            }
        ),
    )
