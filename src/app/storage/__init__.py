"""File and image storage.

The business layer stores and retrieves files through the
:class:`~app.storage.base.FileStorage` protocol and holds only a *storage key*
(``pets/2026/01/ab12....jpg``) -- never a filesystem path, bucket name or URL. Swapping
local disk for S3 is then a settings change plus one adapter, with no changes to models,
services or routes.

What is deliberately **not** built yet: image resizing, format conversion, virus
scanning, CDN signing, async post-processing pipelines. Those are a product feature.
The extension point is here so that adding them later does not require restructuring.
"""

from app.storage.base import FileStorage, StoredFile, build_storage_key
from app.storage.factory import get_storage

__all__ = ["FileStorage", "StoredFile", "build_storage_key", "get_storage"]
