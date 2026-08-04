"""ORM statement shape for Neon current discovery and direction choices."""

from sqlalchemy.sql.elements import TextClause

from sombreado.store.discovery import (
    current_route_version_statement,
    direction_choices_statement,
    nearby_route_candidates_statement,
    search_route_candidates_statement,
)
from sombreado.store.models import DatasetPointerRecord, RouteDirectionRecord, RouteSegmentRecord


def _compiled_sql(statement) -> str:
    from sqlalchemy.dialects.postgresql import dialect

    return str(statement.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))


def test_search_statement_is_orm_over_current_pointer():
    statement = search_route_candidates_statement(query="3A", limit=8)
    assert not isinstance(statement, TextClause)
    sql = _compiled_sql(statement).lower()
    assert "dataset_pointers" in sql
    assert "role" in sql
    assert "current" in sql
    assert "ilike" in sql


def test_nearby_statement_uses_geography_and_current_pointer():
    statement = nearby_route_candidates_statement(
        lat=-27.6,
        lng=-48.5,
        radius_meters=50,
        limit=5,
    )
    assert not isinstance(statement, TextClause)
    sql = _compiled_sql(statement).lower()
    assert "dataset_pointers" in sql
    assert "st_dwithin" in sql
    assert "st_distance" in sql
    assert RouteSegmentRecord.geom.key == "geom"


def test_direction_choices_statement_reads_current_only():
    statement = direction_choices_statement(route_version_id="version-a")
    assert not isinstance(statement, TextClause)
    sql = _compiled_sql(statement).lower()
    assert "dataset_pointers" in sql
    assert "route_directions" in sql
    assert RouteDirectionRecord.direction_kind.key == "direction_kind"


def test_current_route_version_statement_joins_pointer():
    statement = current_route_version_statement(route_id="route-a")
    assert not isinstance(statement, TextClause)
    sql = _compiled_sql(statement).lower()
    assert "dataset_route_versions" in sql
    assert DatasetPointerRecord.role.key == "role"
    assert "current" in sql
