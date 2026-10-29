from __future__ import annotations

import hashlib
import inspect
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

import anyio

from app.core.errors import NotFoundError, PayloadTooLargeError
from app.storage.base import AsyncReadable, StoredFile, validate_key

CHUNK_SIZE = 64 * 1024


class LocalFileStorage:
    """Filesystem storage for development and single-node deployments.

    Writes go to a temporary file and are then atomically renamed, so a crashed or
    aborted upload can never leave a half-written object under a live key.
    """

    def __init__(self, root: Path, *, public_base_url: str) -> None:
        self._root = root.resolve()
        self._public_base_url = public_base_url.rstrip("/")
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self._root / validate_key(key)).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError(f"Unsafe storage key: {key!r}")
        return path

    async def save(
        self,
        key: str,
        source: AsyncReadable | AsyncIterator[bytes] | BinaryIO,
        *,
        content_type: str,
        max_bytes: int | None = None,
    ) -> StoredFile:
        path = self._path(key)
        await anyio.to_thread.run_sync(lambda: path.parent.mkdir(parents=True, exist_ok=True))
        temp_path = path.with_suffix(path.suffix + ".part")

        digest = hashlib.sha256()
        size = 0
        try:
            async with await anyio.open_file(temp_path, "wb") as handle:
                async for chunk in _iter_chunks(source):
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        raise PayloadTooLargeError(
                            f"Upload exceeds the {max_bytes} byte limit.",
                            extra={"max_bytes": max_bytes},
                        )
                    digest.update(chunk)
                    await handle.write(chunk)
            await anyio.to_thread.run_sync(shutil.move, str(temp_path), str(path))
        except BaseException:
            await anyio.to_thread.run_sync(lambda: temp_path.unlink(missing_ok=True))
            raise

        return StoredFile(
            key=key,
            size_bytes=size,
            content_type=content_type,
            checksum_sha256=digest.hexdigest(),
        )

    async def open(self, key: str) -> AsyncIterator[bytes]:
        path = self._path(key)
        if not path.exists():
            raise NotFoundError.for_resource("File", key)

        async def iterator() -> AsyncIterator[bytes]:
            async with await anyio.open_file(path, "rb") as handle:
                while chunk := await handle.read(CHUNK_SIZE):
                    yield chunk

        return iterator()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await anyio.to_thread.run_sync(lambda: path.unlink(missing_ok=True))

    async def exists(self, key: str) -> bool:
        return await anyio.to_thread.run_sync(self._path(key).exists)

    def url_for(self, key: str, *, expires_in: int | None = None) -> str:
        return f"{self._public_base_url}/{validate_key(key)}"


async def _iter_chunks(
    source: AsyncReadable | AsyncIterator[bytes] | BinaryIO,
) -> AsyncIterator[bytes]:
    """Normalise the three shapes a caller may supply into an async chunk stream.

    The sync branch is deliberately routed through a worker thread: ``UploadFile.file``
    is a ``SpooledTemporaryFile`` that spills to disk above a threshold, so reading it
    directly would block the event loop for the duration of every large upload.
    """
    # NOT isinstance(source, AsyncReadable): a runtime_checkable Protocol only checks
    # that an attribute called `read` exists, so every sync file object matches it and
    # we would then try to await bytes. The callable itself has to be inspected.
    read = getattr(source, "read", None)
    if read is not None and inspect.iscoroutinefunction(read):
        while chunk := await read(CHUNK_SIZE):
            yield chunk
        return
    if hasattr(source, "__aiter__"):
        async for chunk in source:
            yield chunk
        return
    if read is None:  # pragma: no cover - guarded by the type signature
        raise TypeError(f"Unsupported upload source: {type(source).__name__}")
    while chunk := await anyio.to_thread.run_sync(read, CHUNK_SIZE):
        yield chunk
