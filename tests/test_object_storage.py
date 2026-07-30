"""Object Storage adapters for Generation Store backups."""

from __future__ import annotations

from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from sombreado.store.object_storage import DirectoryObjectStorage, S3CompatibleObjectStorage


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.list_calls: list[dict[str, object]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        del Bucket
        self.objects[Key] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        del Bucket
        return {"Body": _BytesBody(self.objects[Key])}

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        self.list_calls.append(kwargs)
        prefix = str(kwargs.get("Prefix", ""))
        keys = sorted(key for key in self.objects if key.startswith(prefix))
        return {
            "Contents": [{"Key": key} for key in keys],
            "IsTruncated": False,
        }

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        del Bucket
        self.objects.pop(Key, None)


class _BytesBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


def test_directory_object_storage_filters_by_prefix(tmp_path: Path) -> None:
    storage = DirectoryObjectStorage(tmp_path)
    storage.upload("sombreado-routes-a.sqlite", b"a")
    storage.upload("other-b.sqlite", b"b")

    assert storage.list_keys(prefix="sombreado-routes") == ["sombreado-routes-a.sqlite"]


def test_s3_compatible_list_keys_passes_prefix_to_list_objects_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeS3Client()
    storage = S3CompatibleObjectStorage(
        bucket="backups",
        endpoint_url="https://example.compat.objectstorage.local",
        access_key="key",
        secret_key="secret",
    )
    monkeypatch.setattr(S3CompatibleObjectStorage, "_client", lambda self: fake)

    storage.upload("sombreado-routes-1.sqlite", b"one")
    storage.upload("other-2.sqlite", b"two")

    keys = storage.list_keys(prefix="sombreado-routes")

    assert keys == ["sombreado-routes-1.sqlite"]
    assert fake.list_calls == [{"Bucket": "backups", "Prefix": "sombreado-routes"}]
    assert storage.download("sombreado-routes-1.sqlite") == b"one"
    storage.delete("sombreado-routes-1.sqlite")
    assert storage.list_keys(prefix="sombreado-routes") == []


def test_s3_compatible_list_keys_paginates_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = S3CompatibleObjectStorage(
        bucket="backups",
        endpoint_url="https://example.compat.objectstorage.local",
        access_key="key",
        secret_key="secret",
    )
    calls: list[dict[str, object]] = []

    class PagingClient:
        def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            if "ContinuationToken" not in kwargs:
                return {
                    "Contents": [{"Key": "sombreado-routes-a.sqlite"}],
                    "IsTruncated": True,
                    "NextContinuationToken": "page-2",
                }
            return {
                "Contents": [{"Key": "sombreado-routes-b.sqlite"}],
                "IsTruncated": False,
            }

    monkeypatch.setattr(S3CompatibleObjectStorage, "_client", lambda self: PagingClient())

    assert storage.list_keys(prefix="sombreado-routes") == [
        "sombreado-routes-a.sqlite",
        "sombreado-routes-b.sqlite",
    ]
    assert calls[0]["Prefix"] == "sombreado-routes"
    assert calls[1]["ContinuationToken"] == "page-2"
    assert calls[1]["Prefix"] == "sombreado-routes"


def test_s3_compatible_reuses_cached_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeS3Client()
    created: list[object] = []

    def fake_boto_client(service_name: str, **kwargs: object) -> FakeS3Client:
        del service_name, kwargs
        created.append(object())
        return fake

    monkeypatch.setattr("boto3.client", fake_boto_client)
    storage = S3CompatibleObjectStorage(
        bucket="backups",
        endpoint_url="https://example.compat.objectstorage.local",
        access_key="key",
        secret_key="secret",
    )

    storage.upload("sombreado-routes-1.sqlite", b"one")
    assert storage.download("sombreado-routes-1.sqlite") == b"one"
    assert storage.list_keys(prefix="sombreado-routes") == ["sombreado-routes-1.sqlite"]
    storage.delete("sombreado-routes-1.sqlite")

    assert len(created) == 1


def test_s3_compatible_repr_omits_credentials() -> None:
    storage = S3CompatibleObjectStorage(
        bucket="backups",
        endpoint_url="https://example.compat.objectstorage.local",
        access_key="AKIA_SECRET_ACCESS",
        secret_key="super-secret-value",
    )

    text = repr(storage)

    assert "AKIA_SECRET_ACCESS" not in text
    assert "super-secret-value" not in text
    assert "backups" in text


def test_s3_download_missing_object_raises_file_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingClient:
        def get_object(self, **kwargs: object) -> dict[str, object]:
            del kwargs
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
                "GetObject",
            )

    storage = S3CompatibleObjectStorage(
        bucket="backups",
        endpoint_url="https://example.compat.objectstorage.local",
        access_key="key",
        secret_key="secret",
    )
    monkeypatch.setattr(S3CompatibleObjectStorage, "_client", lambda self: MissingClient())

    with pytest.raises(FileNotFoundError, match="missing.sqlite"):
        storage.download("missing.sqlite")
