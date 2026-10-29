from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.storage.base import FileStorage
from app.storage.local import LocalFileStorage


def build_storage(settings: Settings) -> FileStorage:
    match settings.storage_backend:
        case "local":
            return LocalFileStorage(
                settings.storage_local_path,
                public_base_url=settings.storage_public_base_url,
            )
        case "s3":
            # Extension point. Implement app/storage/s3.py against the FileStorage
            # protocol (aioboto3 or an httpx-based signer), add the credential settings
            # to Settings, and return it here. Nothing else in the codebase changes.
            raise NotImplementedError(
                "The S3 storage backend is not implemented yet. See app/storage/factory.py."
            )
        case _:  # pragma: no cover - Settings validation makes this unreachable
            raise ValueError(f"Unknown storage backend: {settings.storage_backend}")


_storage: FileStorage | None = None


def init_storage(settings: Settings) -> FileStorage:
    global _storage
    if _storage is None:
        _storage = build_storage(settings)
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None


def get_storage() -> FileStorage:
    if _storage is None:
        return init_storage(get_settings())
    return _storage


StorageDep = Annotated[FileStorage, Depends(get_storage)]
