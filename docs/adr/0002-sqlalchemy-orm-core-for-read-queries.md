# SQLAlchemy ORM/Core for Read Queries

## Status

Superseded for passenger reads by the Generation Store SQLite path. Kept for historical PostGIS `RouteReadService` code until that module is deleted.

## Historical decision

Sombreado Service read queries used SQLAlchemy ORM/Core expressions instead of textual SQL while the service was read-only over scraper-owned PostGIS tables. Pydantic remained the API/read DTO validation boundary.

Mapped SQLAlchemy classes represented database records. API response models and read DTOs stayed separate from ORM mappings.

## Current passenger reads

Passenger Route Discovery, Direction Choices, Route Geometry, and Advice read the Generation Store through parameterized SQLite SQL in `sombreado.store` (for example `discovery.py`). Do not reintroduce PostGIS / SQLAlchemy passenger reads. New passenger-facing store reads should stay on the SQLite `current` pointer seam.
