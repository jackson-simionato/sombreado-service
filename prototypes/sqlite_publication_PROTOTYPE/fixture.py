"""Verified fixture loading for the SQLite publication PROTOTYPE."""

from __future__ import annotations

import gzip
from hashlib import sha256
from pathlib import Path

from consorcio_fenix_scraper.domain import RouteSnapshot

FIXTURE_SHA256 = "817aa8ee9c3ef0d6a76c9795191097a88de5129247205e1a988d94c7981dc300"
FIXTURE_SNAPSHOT_COUNT = 186
_HASH_CHUNK_BYTES = 1024 * 1024


def load_snapshots(path: Path) -> list[RouteSnapshot]:
    """Verify the compressed fixture, then stream and validate its JSON lines."""
    digest = sha256()
    with path.open("rb") as compressed:
        while chunk := compressed.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    if digest.hexdigest() != FIXTURE_SHA256:
        raise RuntimeError(f"fixture SHA-256 mismatch: {path}")

    snapshots: list[RouteSnapshot] = []
    with gzip.open(path, mode="rt", encoding="utf-8") as fixture:
        for line in fixture:
            snapshots.append(RouteSnapshot.model_validate_json(line))

    snapshots.sort(key=lambda snapshot: snapshot.route.code)
    if len(snapshots) != FIXTURE_SNAPSHOT_COUNT:
        raise RuntimeError(f"fixture snapshot count mismatch: expected {FIXTURE_SNAPSHOT_COUNT}, got {len(snapshots)}")
    return snapshots
