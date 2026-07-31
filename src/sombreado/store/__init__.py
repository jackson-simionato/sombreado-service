"""Durable datastore access.

Route Discovery and Direction Choices read the SQLite Generation Store `current`
pointer. Route Geometry and Advice still use the PostGIS reader role until #37.
"""

from sombreado.store.generation import GenerationStore, ScrapeLeaseHeldError

__all__ = ["GenerationStore", "ScrapeLeaseHeldError"]
