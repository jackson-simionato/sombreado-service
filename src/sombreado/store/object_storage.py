"""Object Storage seam for Generation Store backups."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class ObjectStorage(Protocol):
    def upload(self, key: str, data: bytes) -> None: ...

    def download(self, key: str) -> bytes: ...

    def list_keys(self) -> list[str]: ...

    def delete(self, key: str) -> None: ...


@dataclass
class MemoryObjectStorage:
    """In-memory Object Storage used by tests."""

    _objects: dict[str, bytes] = field(default_factory=dict)

    def upload(self, key: str, data: bytes) -> None:
        self._objects[key] = data

    def download(self, key: str) -> bytes:
        try:
            return self._objects[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc

    def list_keys(self) -> list[str]:
        return sorted(self._objects)

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)


@dataclass(frozen=True)
class DirectoryObjectStorage:
    """Local directory stand-in for Object Storage (dev / offline drills)."""

    root: Path

    def upload(self, key: str, data: bytes) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def download(self, key: str) -> bytes:
        path = self._path_for(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def list_keys(self) -> list[str]:
        if not self.root.exists():
            return []
        keys: list[str] = []
        for path in self.root.rglob("*"):
            if path.is_file():
                keys.append(path.relative_to(self.root).as_posix())
        return sorted(keys)

    def delete(self, key: str) -> None:
        path = self._path_for(key)
        path.unlink(missing_ok=True)

    def _path_for(self, key: str) -> Path:
        relative = Path(key)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe object key: {key!r}")
        return self.root / relative


@dataclass(frozen=True)
class S3CompatibleObjectStorage:
    """Oracle Object Storage via the Amazon S3 Compatibility API."""

    bucket: str
    endpoint_url: str
    access_key: str
    secret_key: str
    region: str = "sa-saopaulo-1"

    def _client(self):
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )

    def upload(self, key: str, data: bytes) -> None:
        self._client().put_object(Bucket=self.bucket, Key=key, Body=data)

    def download(self, key: str) -> bytes:
        response = self._client().get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def list_keys(self) -> list[str]:
        client = self._client()
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, object] = {"Bucket": self.bucket}
            if token is not None:
                kwargs["ContinuationToken"] = token
            response = client.list_objects_v2(**kwargs)
            for item in response.get("Contents", []):
                keys.append(item["Key"])
            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")
        return sorted(keys)

    def delete(self, key: str) -> None:
        self._client().delete_object(Bucket=self.bucket, Key=key)
