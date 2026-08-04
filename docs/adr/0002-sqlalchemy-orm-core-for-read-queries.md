# SQLAlchemy ORM/Core for Read Queries

## Status

Accepted for Neon/PostGIS Generation Store passenger reads.

## Decision

Passenger reads of the Neon **Generation Store** `current` pointer use **full SQLAlchemy ORM** mapped models.

- SQLAlchemy expressions / `func` are allowed for PostGIS (for example `ST_DWithin` / geography). Raw SQL strings are not the default passenger-read style.
- **Pydantic** remains the API / DTO boundary; ORM mappings are not public browser schemas.
- There is **no dual SQLite passenger-read path**.

## Consequences

- `sombreado.store.models` maps the Generation Store schema (`dataset_pointers`, `dataset_route_versions`, geography `geom`, and related tables).
- **Route Discovery**, **Direction Choices**, **Route Geometry**, and **Advice** queries are ORM selects in `sombreado.store.discovery`, served through `CurrentRouteReadService`.
- Segment and direction-membership helpers for geometry and advice read only the `current` pointer via ORM; there is no dual SQLite passenger-read path.
- The historical scraper-owned PostGIS `RouteReadService` framing is retired; do not reintroduce `is_current`-flag passenger reads over scraper tables.
