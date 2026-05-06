from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RouteRecord(Base):
    __tablename__ = "routes"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean)


class RouteVersionRecord(Base):
    __tablename__ = "route_versions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    route_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("routes.id"))
    is_current: Mapped[bool] = mapped_column(Boolean)


class RouteDirectionRecord(Base):
    __tablename__ = "route_directions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    route_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_versions.id"))
    name: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer)


class RouteSegmentRecord(Base):
    __tablename__ = "route_segments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    route_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_versions.id"))
    route_direction_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_directions.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    geometry: Mapped[object] = mapped_column(Geometry("LINESTRING", srid=4326))
    bearing_degrees: Mapped[float] = mapped_column(Float)
    distance_meters: Mapped[float] = mapped_column(Float)
    cumulative_distance_meters: Mapped[float] = mapped_column(Float)


class ServiceDirectionRecord(Base):
    __tablename__ = "service_directions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    route_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_versions.id"))
    route_direction_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("route_directions.id"))
    departure_label: Mapped[str] = mapped_column(Text)
