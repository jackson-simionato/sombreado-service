"""ORM statement shape for Neon current passenger reads (discovery through advice)."""

from __future__ import annotations

import re

from sqlalchemy.sql.elements import TextClause

from sombreado.store.discovery import (
    PUBLIC_DIRECTION_LABEL_CONFIDENCES,
    current_route_segments_statement,
    current_route_version_statement,
    departure_labels_statement,
    direction_choices_statement,
    direction_hints_statement,
    nearby_route_candidates_statement,
    route_direction_membership_statement,
    search_route_candidates_statement,
)

_CURRENT_POINTER_JOIN = (
    "JOIN dataset_pointers ON dataset_pointers.generation_id = "
    "dataset_route_versions.generation_id AND dataset_pointers.role = 'current'"
)


def _compiled_sql(statement) -> str:
    from sqlalchemy.dialects.postgresql import dialect

    return str(statement.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _assert_orm_current_pointer(statement) -> str:
    assert not isinstance(statement, TextClause)
    sql = _normalize(_compiled_sql(statement))
    assert _CURRENT_POINTER_JOIN in sql
    return sql


def test_search_statement_joins_current_pointer_and_filters_query():
    sql = _assert_orm_current_pointer(search_route_candidates_statement(query="3A", limit=8))
    assert "FROM routes JOIN dataset_route_versions ON dataset_route_versions.route_id = routes.id" in sql
    assert "WHERE routes.code ILIKE '%%3A%%' OR routes.name ILIKE '%%3A%%'" in sql
    assert sql.endswith("LIMIT 8")


def test_nearby_statement_joins_current_pointer_and_uses_geography():
    sql = _assert_orm_current_pointer(
        nearby_route_candidates_statement(
            lat=-27.6,
            lng=-48.5,
            radius_meters=50,
            limit=5,
        )
    )
    assert "WITH nearby_segments AS MATERIALIZED" in sql
    assert "FROM route_segments WHERE ST_DWithin(route_segments.geom," in sql
    assert sql.index("FROM route_segments") < sql.index("FROM nearby_segments JOIN dataset_route_versions")
    assert "min(ST_Distance(nearby_segments.geom," in sql
    assert "ST_MakePoint(-48.5, -27.6)" in sql
    assert "AS geography" in sql
    assert sql.endswith("LIMIT 5")


def test_direction_choices_statement_joins_current_pointer():
    sql = _assert_orm_current_pointer(direction_choices_statement(route_version_id="version-a"))
    assert "FROM route_directions JOIN dataset_route_versions" in sql
    assert "WHERE route_directions.route_version_id = 'version-a'" in sql
    assert "ORDER BY route_directions.sequence ASC" in sql


def test_current_route_version_statement_joins_current_pointer():
    sql = _assert_orm_current_pointer(current_route_version_statement(route_id="route-a"))
    assert "FROM dataset_route_versions" in sql
    assert "WHERE dataset_route_versions.route_id = 'route-a'" in sql


def test_departure_labels_statement_filters_public_confidence_on_current():
    sql = _assert_orm_current_pointer(departure_labels_statement(route_version_id="version-a"))
    confidence_list = ", ".join(f"'{value}'" for value in PUBLIC_DIRECTION_LABEL_CONFIDENCES)
    assert f"service_directions.confidence IN ({confidence_list})" in sql
    assert "service_directions.route_direction_id IS NOT NULL" in sql
    assert "WHERE" in sql and "route_directions.route_version_id = 'version-a'" in sql
    assert "ORDER BY route_directions.sequence ASC, service_directions.sequence ASC" in sql


def test_direction_hints_statement_filters_version_ids_on_current():
    sql = _assert_orm_current_pointer(direction_hints_statement(version_ids=["v1", "v2"]))
    assert "route_directions.route_version_id IN ('v1', 'v2')" in sql
    assert "service_directions.confidence IN ('high', 'medium')" in sql
    assert (
        "ORDER BY route_directions.route_version_id ASC, route_directions.sequence ASC, service_directions.sequence ASC"
    ) in sql


def test_route_direction_membership_statement_predicates_on_current():
    sql = _assert_orm_current_pointer(
        route_direction_membership_statement(
            route_version_id="version-a",
            route_direction_id="direction-a",
        )
    )
    assert "WHERE route_directions.route_version_id = 'version-a' AND route_directions.id = 'direction-a'" in sql


def test_current_route_segments_statement_orders_by_sequence_on_current():
    sql = _assert_orm_current_pointer(
        current_route_segments_statement(
            route_version_id="version-a",
            route_direction_id="direction-a",
        )
    )
    assert "FROM route_segments JOIN dataset_route_versions" in sql
    assert (
        "WHERE route_segments.route_version_id = 'version-a' AND route_segments.route_direction_id = 'direction-a'"
    ) in sql
    assert sql.endswith("ORDER BY route_segments.sequence ASC")
