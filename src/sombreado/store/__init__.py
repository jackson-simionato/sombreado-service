"""Durable datastore access.

Passenger Route Discovery, Direction Choices, Route Geometry, and Advice read the
SQLite Generation Store `current` pointer.
"""

from sombreado.store.generation import GenerationStore, ScrapeLeaseHeldError

__all__ = ["GenerationStore", "ScrapeLeaseHeldError"]
