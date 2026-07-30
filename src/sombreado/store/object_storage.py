"""Object Storage seam for Generation Store backups."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from botocore.exceptions import BotoCoreError, ClientError

_S3_CLIENT_ERRORS = (BotoCoreError, ClientError)
_S3_MISSING_CODES = frozenset({"NoSuchKey", "404", "NotFound"})


class ObjectStorage(Protocol):
    def upload(self, key: str, data: bytes) -> None: ...

    def download(self, key: str) -> bytes: ...

    def list_keys(self, *, prefix: str = "") -> list[str]: ...

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

    def list_keys(self, *, prefix: str = "") -> list[str]:
        keys = [key for key in self._objects if key.startswith(prefix)]
        return sorted(keys)

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

    def list_keys(self, *, prefix: str = "") -> list[str]:
        if not self.root.exists():
            return []
        keys: list[str] = []
        for path in self.root.rglob("*"):
            if path.is_file():
                key = path.relative_to(self.root).as_posix()
                if key.startswith(prefix):
                    keys.append(key)
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
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    region: str = "sa-saopaulo-1"
    _cached_client: Any = field(default=None, init=False, repr=False, compare=False)

    def _client(self):
        if self._cached_client is None:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
            )
            object.__setattr__(self, "_cached_client", client)
        return self._cached_client

    def upload(self, key: str, data: bytes) -> None:
        try:
            self._client().put_object(Bucket=self.bucket, Key=key, Body=data)
        except _S3_CLIENT_ERRORS as exc:
            raise RuntimeError(f"s3 upload failed for {key!r}: {exc}") from exc

    def download(self, key: str) -> bytes:
        try:
            response = self._client().get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            if _is_missing_object(exc):
                raise FileNotFoundError(key) from exc
            raise RuntimeError(f"s3 download failed for {key!r}: {exc}") from exc
        except BotoCoreError as exc:
            raise RuntimeError(f"s3 download failed for {key!r}: {exc}") from exc

    def list_keys(self, *, prefix: str = "") -> list[str]:
        client = self._client()
        keys: list[str] = []
        token: str | None = None
        try:
            while True:
                kwargs: dict[str, object] = {"Bucket": self.bucket}
                if prefix:
                    kwargs["Prefix"] = prefix
                if token is not None:
                    kwargs["ContinuationToken"] = token
                response = client.list_objects_v2(**kwargs)
                for item in response.get("Contents", []):
                    keys.append(item["Key"])
                if not response.get("IsTruncated"):
                    break
                token = response.get("NextContinuationToken")
        except _S3_CLIENT_ERRORS as exc:
            raise RuntimeError(f"s3 list failed for prefix {prefix!r}: {exc}") from exc
        return sorted(keys)

    def delete(self, key: str) -> None:
        try:
            self._client().delete_object(Bucket=self.bucket, Key=key)
        except _S3_CLIENT_ERRORS as exc:
            raise RuntimeError(f"s3 delete failed for {key!r}: {exc}") from exc


def _is_missing_object(exc: ClientError) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    return code in _S3_MISSING_CODES
