"""SQLAlchemy ORM mappings for the Neon/PostGIS Generation Store."""

from __future__ import annotations

from geoalchemy2 import Geography
from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RouteRecord(Base):
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    fare_region: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_changed: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_current: Mapped[int] = mapped_column(Integer)


class RouteVersionRecord(Base):
    __tablename__ = "route_versions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("routes.id"))
    source_hash: Mapped[str] = mapped_column(Text)
    map_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_url: Mapped[str] = mapped_column(Text)
    map_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_current: Mapped[int] = mapped_column(Integer)


class RouteDirectionRecord(Base):
    __tablename__ = "route_directions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    route_version_id: Mapped[str] = mapped_column(Text, ForeignKey("route_versions.id"))
    name: Mapped[str] = mapped_column(Text)
    direction_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer)
    geometry: Mapped[str] = mapped_column(Text)
    advice_segments: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")


class ServiceDirectionRecord(Base):
    __tablename__ = "service_directions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    route_version_id: Mapped[str] = mapped_column(Text, ForeignKey("route_versions.id"))
    route_direction_id: Mapped[str | None] = mapped_column(Text, ForeignKey("route_directions.id"), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer)
    departure_label: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    direction_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text)


class RouteSegmentRecord(Base):
    __tablename__ = "route_segments"

    public_id: Mapped[str] = mapped_column(Text, primary_key=True)
    route_version_id: Mapped[str] = mapped_column(Text, ForeignKey("route_versions.id"))
    route_direction_id: Mapped[str] = mapped_column(Text, ForeignKey("route_directions.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    source_segment_sequence: Mapped[int] = mapped_column(Integer)
    source_fraction_start: Mapped[float] = mapped_column(Float)
    source_fraction_end: Mapped[float] = mapped_column(Float)
    geometry: Mapped[str] = mapped_column(Text)
    geom: Mapped[object] = mapped_column(Geography(geometry_type="LINESTRING", srid=4326))
    bearing_degrees: Mapped[float] = mapped_column(Float)
    distance_meters: Mapped[float] = mapped_column(Float)
    cumulative_distance_meters: Mapped[float] = mapped_column(Float)


class DatasetGenerationRecord(Base):
    __tablename__ = "dataset_generations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text)


class DatasetRouteVersionRecord(Base):
    __tablename__ = "dataset_route_versions"

    generation_id: Mapped[str] = mapped_column(Text, ForeignKey("dataset_generations.id"), primary_key=True)
    route_id: Mapped[str] = mapped_column(Text, ForeignKey("routes.id"), primary_key=True)
    route_version_id: Mapped[str] = mapped_column(Text, ForeignKey("route_versions.id"))


class DatasetPointerRecord(Base):
    __tablename__ = "dataset_pointers"

    role: Mapped[str] = mapped_column(Text, primary_key=True)
    generation_id: Mapped[str] = mapped_column(Text, ForeignKey("dataset_generations.id"))
