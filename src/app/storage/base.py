from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

_SAFE_SEGMENT = re.compile(r"[^a-z0-9-]+")

# Extensions are derived from the *validated* content type, never from the client's
# filename. A client that uploads `payload.html` while claiming `image/png` must not be
# able to place a `.html` object in a bucket that is later served over HTTP -- that is
# stored XSS, and it is the single most common file-upload vulnerability.
#
# Callers validate the content type against their own allowlist first; anything not
# listed here is stored as `.bin`, which is inert wherever it is served from.
CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "application/pdf": ".pdf",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/zip": ".zip",
}

DEFAULT_EXTENSION = ".bin"


@dataclass(frozen=True, slots=True)
class StoredFile:
    """What a service persists after an upload: the key is the durable reference.

    ``original_filename`` is retained as *metadata only* -- it is display text, it never
    influences where the object is written.
    """

    key: str
    size_bytes: int
    content_type: str
    original_filename: str | None = None
    checksum_sha256: str | None = None


class AsyncReadable(Protocol):
    """Anything with an async ``read(size)`` -- notably Starlette's ``UploadFile``.

    Intentionally *not* ``@runtime_checkable``: a runtime-checkable Protocol only
    verifies that an attribute of that name exists, so every synchronous file object
    would satisfy it and callers would end up awaiting bytes.
    """

    async def read(self, size: int = -1) -> bytes: ...


@runtime_checkable
class FileStorage(Protocol):
    async def save(
        self,
        key: str,
        source: AsyncReadable | AsyncIterator[bytes],
        *,
        content_type: str,
        max_bytes: int | None = None,
    ) -> StoredFile: ...

    async def open(self, key: str) -> AsyncIterator[bytes]: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    def url_for(self, key: str, *, expires_in: int | None = None) -> str:
        """Return a retrievable URL. Backends that support it return a signed URL."""
        ...


def build_storage_key(
    namespace: str,
    *,
    content_type: str,
    at: datetime | None = None,
) -> str:
    """Generate a collision-free, date-partitioned, traversal-safe key.

    The name is fully generated: a random UUID plus an extension chosen from the
    content type. No part of it is attacker-controlled, so neither a crafted filename
    nor a crafted namespace can escape the prefix or change the served content type.
    """
    moment = at or datetime.now(UTC)
    extension = CONTENT_TYPE_EXTENSIONS.get(
        content_type.split(";")[0].strip().lower(), DEFAULT_EXTENSION
    )
    safe_namespace = _SAFE_SEGMENT.sub("-", namespace.lower()).strip("-") or "files"
    return f"{safe_namespace}/{moment:%Y/%m}/{uuid.uuid4().hex}{extension}"


def validate_key(key: str) -> str:
    """Reject anything that could escape the storage root when joined to a path."""
    if not key or key.startswith("/") or "\\" in key or ".." in key.split("/"):
        raise ValueError(f"Unsafe storage key: {key!r}")
    if "\x00" in key:
        raise ValueError("Unsafe storage key: contains a null byte")
    return key
