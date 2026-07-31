"""Nearby reads against published current generation."""

from pathlib import Path

from pytest import approx

from sombreado.store.generation import GenerationStore
from sombreado.store.nearby import find_nearby_routes
from sombreado.store.sample_data import sample_generation_rows


def test_nearby_reads_only_current_and_includes_on_route_point(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
    store.stage("gen-a", sample_generation_rows(generation_suffix="a"))
    store.validate("gen-a")
    store.publish("gen-a")

    # Point on the first sample segment (PostGIS case distance ≈ 0).
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


def test_nearby_excludes_routes_outside_radius(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
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


def test_nearby_ignores_staging_generation(tmp_path: Path):
    store = GenerationStore(tmp_path / "routes.sqlite")
    store.migrate()
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
