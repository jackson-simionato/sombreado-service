# SQLAlchemy ORM/Core for Read Queries

Sombreado Service read queries will use SQLAlchemy ORM/Core expressions instead of textual SQL. The service remains read-only over scraper-owned database tables, and Pydantic remains the API/read DTO validation boundary.

The mapped SQLAlchemy classes represent database records. API response models and read DTOs stay in `app.schemas`; we will not merge the database mapping and response contracts with SQLModel or similar dual-purpose models.

This keeps route discovery and geometry reads tied to typed table and column references while still doing filtering, sorting, limiting, PostGIS distance predicates, and departure-label aggregation in PostgreSQL. Raw textual SQL is not part of application read code. Documentation and historical plans may still contain SQL snippets, but code review should reject new app reads built with `text("""...""")`.
