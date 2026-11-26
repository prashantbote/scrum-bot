"""Blob storage for reports (HTML/PDF): local disk or any S3 API (MinIO, Ceph, SeaweedFS)."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Protocol


class BlobStore(Protocol):
    name: str

    async def put(self, key: str, data: bytes, content_type: str) -> str: ...
    async def get(self, key: str) -> bytes | None: ...
    async def delete(self, key: str) -> None: ...


class LocalBlobStore:
    name = "local"

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        p = (self._root / key).resolve()
        if self._root not in p.parents:
            raise ValueError("invalid blob key")
        return p

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(p.write_bytes, data)
        return f"local://{key}"

    async def get(self, key: str) -> bytes | None:
        p = self._path(key)
        return await asyncio.to_thread(p.read_bytes) if p.exists() else None

    async def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            await asyncio.to_thread(p.unlink)


class S3BlobStore:
    name = "s3"

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False) -> None:
        from minio import Minio

        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._bucket = bucket
        self._ready = False

    def _ensure(self) -> None:
        if not self._ready:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
            self._ready = True

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        def _put() -> None:
            self._ensure()
            self._client.put_object(self._bucket, key, io.BytesIO(data), len(data), content_type=content_type)

        await asyncio.to_thread(_put)
        return f"s3://{self._bucket}/{key}"

    async def get(self, key: str) -> bytes | None:
        def _get() -> bytes | None:
            from minio.error import S3Error

            try:
                resp = self._client.get_object(self._bucket, key)
            except S3Error:
                return None
            try:
                return bytes(resp.read())
            finally:
                resp.close()
                resp.release_conn()

        return await asyncio.to_thread(_get)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self._bucket, key)


def key_from_uri(uri: str) -> str:
    if uri.startswith("local://"):
        return uri[len("local://") :]
    if uri.startswith("s3://"):
        return uri.split("/", 3)[3]
    return uri
