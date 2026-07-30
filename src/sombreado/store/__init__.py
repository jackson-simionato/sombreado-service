"""Durable datastore access.

Passenger API reads still use the PostGIS reader role until cutover.
The SQLite generation store is owned here for fixture publish and upcoming scrape.
"""

from sombreado.store.generation import GenerationStore, ScrapeLeaseHeldError

__all__ = ["GenerationStore", "ScrapeLeaseHeldError"]
