"""Fixture publish path without Consórcio or PostGIS."""

import json
from pathlib import Path

from typer.testing import CliRunner

from sombreado.cli.main import app
from sombreado.store.fixture_publish import publish_demo_fixture
from sombreado.store.sample_data import sample_generation_rows


def test_publish_demo_fixture_sets_current_readable_via_store(tmp_path: Path):
    database_path = tmp_path / "demo.sqlite"
    published_id, store = publish_demo_fixture(database_path, generation_id="demo-1")

    assert published_id == "demo-1"
    assert store.current_generation() == "demo-1"
    assert store.current_route_version_ids()
    nearby = store.nearby(
        lat=-27.58967541174793,
        lng=-48.53426644737102,
        radius_meters=50,
    )
    assert [row.route_code for row in nearby] == ["1DEMO"]


def test_publish_fixture_cli_reads_json_and_sets_current(tmp_path: Path):
    database_path = tmp_path / "cli.sqlite"
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps(sample_generation_rows(generation_suffix="cli")),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "publish-fixture",
            "--database",
            str(database_path),
            "--fixture",
            str(fixture_path),
            "--generation-id",
            "cli-gen",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "published generation=cli-gen" in result.stdout
    assert "current=cli-gen" in result.stdout
