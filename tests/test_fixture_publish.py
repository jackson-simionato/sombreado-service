"""Fixture publish path without Consórcio against Neon/PostGIS."""

import json
from pathlib import Path

from typer.testing import CliRunner

from sombreado.cli.main import app
from sombreado.config import get_settings
from sombreado.store.fixture_publish import publish_demo_fixture
from sombreado.store.nearby import find_nearby_routes
from sombreado.store.sample_data import sample_generation_rows


def test_publish_demo_fixture_sets_current_readable_via_store(database_url: str):
    published_id, store = publish_demo_fixture(database_url, generation_id="demo-1")

    assert published_id == "demo-1"
    assert store.current_generation() == "demo-1"
    assert store.current_route_version_ids()
    with store.session() as session:
        nearby = find_nearby_routes(
            session,
            lat=-27.58967541174793,
            lng=-48.53426644737102,
            radius_meters=50,
        )
    assert [row.route_code for row in nearby] == ["1DEMO"]


def test_publish_fixture_cli_reads_json_and_sets_current(database_url: str, tmp_path: Path, monkeypatch):
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps(sample_generation_rows(generation_suffix="cli")),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "publish-fixture",
            "--fixture",
            str(fixture_path),
            "--generation-id",
            "cli-gen",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "published generation=cli-gen" in result.stdout
    assert "current=cli-gen" in result.stdout
