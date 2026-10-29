from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.core.errors import PayloadTooLargeError
from app.storage.base import build_storage_key, validate_key
from app.storage.local import LocalFileStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path, public_base_url="http://localhost/static")


def test_keys_never_reuse_the_uploaded_filename():
    key = build_storage_key("pets", content_type="image/jpeg")
    assert key.startswith("pets/")
    assert key.endswith(".jpg")


def test_extension_comes_from_the_content_type_not_the_client():
    """A client claiming image/png must not be able to place a .html object."""
    key = build_storage_key("pets", content_type="image/png")
    assert key.endswith(".png")
    assert "html" not in key


def test_unknown_content_types_are_stored_inert():
    assert build_storage_key("pets", content_type="image/svg+xml").endswith(".bin")
    assert build_storage_key("pets", content_type="text/html").endswith(".bin")


def test_namespace_cannot_escape_the_prefix():
    assert build_storage_key("../../etc", content_type="image/jpeg").startswith("etc/")


@pytest.mark.parametrize("bad", ["/abs", "a/../../b", ""])
def test_unsafe_keys_are_rejected(bad: str):
    with pytest.raises(ValueError, match="Unsafe storage key"):
        validate_key(bad)


async def test_save_and_read_back(storage: LocalFileStorage):
    stored = await storage.save(
        "pets/2026/01/a.txt", io.BytesIO(b"hello"), content_type="text/plain"
    )
    assert stored.size_bytes == 5
    assert stored.checksum_sha256 is not None
    assert await storage.exists(stored.key)

    chunks = [chunk async for chunk in await storage.open(stored.key)]
    assert b"".join(chunks) == b"hello"


async def test_oversized_upload_is_rejected_and_leaves_nothing_behind(storage: LocalFileStorage):
    with pytest.raises(PayloadTooLargeError):
        await storage.save(
            "pets/2026/01/big.bin",
            io.BytesIO(b"x" * 100),
            content_type="application/octet-stream",
            max_bytes=10,
        )
    assert not await storage.exists("pets/2026/01/big.bin")


async def test_delete_is_idempotent(storage: LocalFileStorage):
    await storage.delete("pets/2026/01/missing.txt")
