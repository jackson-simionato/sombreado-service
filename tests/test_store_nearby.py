"""Nearby reads against published current generation."""

from pytest import approx

from sombreado.store.generation import GenerationStore
from sombreado.store.nearby import find_nearby_routes
from sombreado.store.sample_data import sample_generation_rows


def test_nearby_reads_only_current_and_includes_on_route_point(store: GenerationStore):
    store.stage("gen-a", sample_generation_rows(generation_suffix="a"))
    store.validate("gen-a")
    store.publish("gen-a")

    # Point on the first sample segment (PostGIS geography distance ≈ 0).
    with store.connection() as connection:
        results = find_nearby_routes(
            connection,
            lat=-27.58967541174793,
            lng=-48.53426644737102,
            radius_meters=50,
        )

    assert len(results) == 1
    assert results[0].route_code == "1A"
    assert results[0].distance_meters == approx(0.0, abs=0.01)


def test_nearby_excludes_routes_outside_radius(store: GenerationStore):
    store.stage("gen-a", sample_generation_rows(generation_suffix="a"))
    store.validate("gen-a")
    store.publish("gen-a")

    with store.connection() as connection:
        results = find_nearby_routes(
            connection,
            lat=-27.0,
            lng=-48.0,
            radius_meters=10,
        )

    assert results == ()


def test_nearby_ignores_staging_generation(store: GenerationStore):
    store.stage("gen-a", sample_generation_rows(generation_suffix="a"))
    store.validate("gen-a")
    store.publish("gen-a")
    store.stage("gen-b", sample_generation_rows(generation_suffix="b"))

    with store.connection() as connection:
        results = find_nearby_routes(
            connection,
            lat=-27.58967541174793,
            lng=-48.53426644737102,
            radius_meters=50,
        )

    assert [row.route_code for row in results] == ["1A"]


def test_nearby_skips_candidates_with_missing_distance(store: GenerationStore, monkeypatch):
    from sombreado.store import nearby as nearby_module
    from sombreado.store.discovery import RouteCandidateRow

    monkeypatch.setattr(
        nearby_module,
        "find_nearby_route_candidates",
        lambda *_args, **_kwargs: (
            RouteCandidateRow(
                route_id="r1",
                route_version_id="v1",
                route_code="110",
                route_name="Keep",
                direction_hints=(),
                distance_meters=12.5,
            ),
            RouteCandidateRow(
                route_id="r2",
                route_version_id="v2",
                route_code="120",
                route_name="Drop",
                direction_hints=(),
                distance_meters=None,
            ),
        ),
    )

    with store.connection() as connection:
        results = find_nearby_routes(connection, lat=-27.6, lng=-48.5, radius_meters=50)

    assert results == (nearby_module.NearbyRoute(route_code="110", route_name="Keep", distance_meters=12.5),)
