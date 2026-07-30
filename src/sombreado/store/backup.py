"""SQLite online backup, integrity, restore for the Generation Store."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from sombreado.store.object_storage import ObjectStorage

DEFAULT_BACKUP_RETAIN = 7


class IntegrityError(RuntimeError):
    """Raised when a SQLite integrity check fails."""


class Alerter(Protocol):
    def alert(self, message: str) -> None: ...


@dataclass(frozen=True)
class BackupJobOutcome:
    status: Literal["uploaded", "failed", "skipped_dirty"]
    object_key: str | None = None
    message: str = ""


def create_online_backup(source: Path, destination: Path) -> Path:
    """Copy ``source`` to ``destination`` using SQLite's online backup API."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)
    return destination


def integrity_check_file(database_path: Path, *, quick: bool = False) -> str:
    """Run integrity_check (or quick_check) on ``database_path``; raise if dirty."""
    pragma = "quick_check" if quick else "integrity_check"
    try:
        with sqlite3.connect(f"file:{database_path.resolve()}?mode=ro", uri=True) as connection:
            rows = connection.execute(f"PRAGMA {pragma}").fetchall()
    except sqlite3.Error as exc:
        raise IntegrityError(f"{pragma} failed for {database_path}: {exc}") from exc
    results = [str(row[0]) for row in rows]
    if results == ["ok"]:
        return "ok"
    detail = "; ".join(results) if results else "no result"
    raise IntegrityError(f"{pragma} failed for {database_path}: {detail}")


def check_live_integrity(database_path: Path, *, alerter: Alerter | None = None) -> bool:
    """Run ``PRAGMA quick_check`` on the live database; alert and return False on failure."""
    try:
        integrity_check_file(database_path, quick=True)
    except IntegrityError as exc:
        _emit(alerter, f"live Generation Store integrity failed: {exc}")
        return False
    return True


def run_backup_job(
    database_path: Path,
    storage: ObjectStorage,
    *,
    work_dir: Path,
    retain: int = DEFAULT_BACKUP_RETAIN,
    key_prefix: str = "sombreado-routes",
    alerter: Alerter | None = None,
) -> BackupJobOutcome:
    """Online-backup → integrity-check → upload → retain last N successful objects.

    Backup failure alerts and returns a failed/skipped outcome; callers (scrape/API)
    must not treat this as a publish gate.
    """
    check_live_integrity(database_path, alerter=alerter)

    work_dir.mkdir(parents=True, exist_ok=True)
    backup_path = work_dir / "backup-candidate.sqlite"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    object_key = f"{key_prefix}-{stamp}-{uuid4().hex[:8]}.sqlite"
    try:
        create_online_backup(database_path, backup_path)
        try:
            integrity_check_file(backup_path)
        except IntegrityError as exc:
            message = f"backup integrity check failed; upload skipped: {exc}"
            _emit(alerter, message)
            return BackupJobOutcome(status="skipped_dirty", message=message)
        storage.upload(object_key, backup_path.read_bytes())
    except Exception as exc:
        message = f"backup job failed: {exc}"
        _emit(alerter, message)
        return BackupJobOutcome(status="failed", message=message)
    finally:
        if backup_path.exists():
            backup_path.unlink()

    try:
        _prune_old_backups(storage, key_prefix=key_prefix, retain=retain)
    except Exception as exc:
        _emit(alerter, f"backup uploaded but prune failed: {exc}")
    return BackupJobOutcome(status="uploaded", object_key=object_key, message="uploaded")


def restore_aside_from_object(
    live_database_path: Path,
    storage: ObjectStorage,
    *,
    aside_dir: Path,
    key_prefix: str = "sombreado-routes",
    work_dir: Path | None = None,
) -> str:
    """Move the live DB aside and install the newest integrity-checked Object Storage object."""
    keys = sorted(key for key in storage.list_keys() if key.startswith(key_prefix))
    if not keys:
        raise FileNotFoundError(f"no backup objects with prefix {key_prefix!r}")

    staging_root = work_dir or aside_dir
    staging_root.mkdir(parents=True, exist_ok=True)
    candidate = staging_root / "restore-candidate.sqlite"

    chosen_key: str | None = None
    for key in reversed(keys):
        candidate.write_bytes(storage.download(key))
        try:
            integrity_check_file(candidate)
        except IntegrityError:
            candidate.unlink(missing_ok=True)
            continue
        chosen_key = key
        break

    if chosen_key is None:
        raise IntegrityError(f"no integrity-checked backup object for prefix {key_prefix!r}")

    aside_dir.mkdir(parents=True, exist_ok=True)
    _aside_live_database(live_database_path, aside_dir)
    live_database_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(candidate), str(live_database_path))
    return chosen_key


def _aside_live_database(live_database_path: Path, aside_dir: Path) -> None:
    """Move the live DB and WAL sidecars aside so restore cannot replay stale WAL."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    for path in (
        live_database_path,
        Path(f"{live_database_path}-wal"),
        Path(f"{live_database_path}-shm"),
    ):
        if not path.exists():
            continue
        aside_path = aside_dir / f"{path.name}.{stamp}"
        shutil.move(str(path), str(aside_path))


def _prune_old_backups(storage: ObjectStorage, *, key_prefix: str, retain: int) -> None:
    """Delete older objects only after a newer good upload is present."""
    keys = [key for key in storage.list_keys() if key.startswith(key_prefix)]
    keys.sort()
    for stale in keys[:-retain] if retain > 0 else keys:
        storage.delete(stale)


def _emit(alerter: Alerter | None, message: str) -> None:
    if alerter is not None:
        alerter.alert(message)
