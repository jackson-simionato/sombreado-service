"""SQLite online backup, integrity checks, Object Storage retention, restore."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sombreado.store.backup import (
    IntegrityError,
    check_live_integrity,
    create_online_backup,
    integrity_check_file,
    restore_aside_from_object,
    run_backup_job,
)
from sombreado.store.object_storage import MemoryObjectStorage


class RecordingAlerter:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def alert(self, message: str) -> None:
        self.messages.append(message)


def _seed_database(path: Path, marker: str = "ok") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker (value) VALUES (?)", (marker,))
        connection.commit()


def _marker(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT value FROM marker").fetchone()
    assert row is not None
    return row[0]


def test_online_backup_is_integrity_ok_and_restorable(tmp_path: Path) -> None:
    source = tmp_path / "live.sqlite"
    backup = tmp_path / "backup.sqlite"
    _seed_database(source, marker="generation-a")

    create_online_backup(source, backup)

    assert integrity_check_file(backup) == "ok"
    assert _marker(backup) == "generation-a"


def test_integrity_check_rejects_corrupt_backup(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"not a sqlite database")

    with pytest.raises(IntegrityError):
        integrity_check_file(corrupt)


def test_backup_job_uploads_integrity_checked_object_restorable_as_database(tmp_path: Path) -> None:
    source = tmp_path / "live.sqlite"
    work_dir = tmp_path / "work"
    _seed_database(source, marker="published-current")
    storage = MemoryObjectStorage()

    outcome = run_backup_job(source, storage, work_dir=work_dir)

    assert outcome.status == "uploaded"
    assert outcome.object_key is not None
    restored = tmp_path / "restored.sqlite"
    restored.write_bytes(storage.download(outcome.object_key))
    assert integrity_check_file(restored) == "ok"
    assert _marker(restored) == "published-current"


def test_backup_job_retains_only_last_seven_successful_uploads(tmp_path: Path) -> None:
    source = tmp_path / "live.sqlite"
    work_dir = tmp_path / "work"
    _seed_database(source, marker="retain")
    storage = MemoryObjectStorage()

    keys: list[str] = []
    for _ in range(9):
        outcome = run_backup_job(source, storage, work_dir=work_dir)
        assert outcome.status == "uploaded"
        assert outcome.object_key is not None
        keys.append(outcome.object_key)

    remaining = storage.list_keys()
    assert len(remaining) == 7
    assert remaining == keys[-7:]
    assert keys[0] not in remaining
    assert keys[1] not in remaining


def test_backup_job_skips_upload_and_alerts_when_backup_is_dirty(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "live.sqlite"
    work_dir = tmp_path / "work"
    _seed_database(source)
    storage = MemoryObjectStorage()
    alerter = RecordingAlerter()

    def fail_check(path: Path, *, quick: bool = False) -> str:
        del path, quick
        raise IntegrityError("integrity_check failed: corrupt")

    monkeypatch.setattr("sombreado.store.backup.integrity_check_file", fail_check)

    outcome = run_backup_job(source, storage, work_dir=work_dir, alerter=alerter)

    assert outcome.status == "skipped_dirty"
    assert storage.list_keys() == []
    assert alerter.messages
    assert "integrity" in alerter.messages[0].lower() or "corrupt" in alerter.messages[0].lower()


def test_backup_job_alerts_on_upload_failure_without_removing_older_objects(tmp_path: Path) -> None:
    source = tmp_path / "live.sqlite"
    work_dir = tmp_path / "work"
    _seed_database(source)
    alerter = RecordingAlerter()
    prior = MemoryObjectStorage()
    prior.upload("sombreado-routes-old.sqlite", b"prior-good")

    class FailingUpload:
        def upload(self, key: str, data: bytes) -> None:
            raise RuntimeError("object storage unavailable")

        def download(self, key: str) -> bytes:
            return prior.download(key)

        def list_keys(self) -> list[str]:
            return prior.list_keys()

        def delete(self, key: str) -> None:
            prior.delete(key)

    outcome = run_backup_job(source, FailingUpload(), work_dir=work_dir, alerter=alerter)

    assert outcome.status == "failed"
    assert prior.list_keys() == ["sombreado-routes-old.sqlite"]
    assert alerter.messages
    assert "unavailable" in alerter.messages[0].lower()


def test_live_integrity_quick_check_alerts_on_failure(tmp_path: Path) -> None:
    live = tmp_path / "live.sqlite"
    live.write_bytes(b"not sqlite")
    alerter = RecordingAlerter()

    ok = check_live_integrity(live, alerter=alerter)

    assert ok is False
    assert alerter.messages


def test_restore_aside_installs_newest_good_object(tmp_path: Path) -> None:
    live = tmp_path / "routes.sqlite"
    aside_dir = tmp_path / "aside"
    _seed_database(live, marker="bad-live")
    (tmp_path / "routes.sqlite-wal").write_text("stale-wal", encoding="utf-8")
    (tmp_path / "routes.sqlite-shm").write_text("stale-shm", encoding="utf-8")
    storage = MemoryObjectStorage()
    storage.upload("sombreado-routes-20260101T000000000000Z-aaaa.sqlite", b"not sqlite")
    good = tmp_path / "good.sqlite"
    _seed_database(good, marker="from-backup")
    storage.upload("sombreado-routes-20260102T000000000000Z-bbbb.sqlite", good.read_bytes())

    restored_key = restore_aside_from_object(live, storage, aside_dir=aside_dir)

    assert restored_key.endswith("bbbb.sqlite")
    assert _marker(live) == "from-backup"
    main_asides = [path for path in aside_dir.iterdir() if path.name.startswith("routes.sqlite.")]
    assert len(main_asides) == 1
    assert _marker(main_asides[0]) == "bad-live"
    assert any(path.name.startswith("routes.sqlite-wal.") for path in aside_dir.iterdir())
    assert any(path.name.startswith("routes.sqlite-shm.") for path in aside_dir.iterdir())
    assert not (tmp_path / "routes.sqlite-wal").exists()
    assert not (tmp_path / "routes.sqlite-shm").exists()


def test_backup_job_keeps_uploaded_status_when_prune_fails(tmp_path: Path) -> None:
    source = tmp_path / "live.sqlite"
    work_dir = tmp_path / "work"
    _seed_database(source)
    alerter = RecordingAlerter()

    class PruneFailStorage(MemoryObjectStorage):
        def delete(self, key: str) -> None:
            raise RuntimeError("delete denied")

    storage = PruneFailStorage()
    for index in range(7):
        storage.upload(f"sombreado-routes-old-{index}.sqlite", b"prior")

    outcome = run_backup_job(source, storage, work_dir=work_dir, alerter=alerter)

    assert outcome.status == "uploaded"
    assert outcome.object_key is not None
    assert outcome.object_key in storage.list_keys()
    assert any("prune" in message.lower() or "delete" in message.lower() for message in alerter.messages)
