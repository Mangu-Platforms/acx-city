"""Storage backend selection (singleton)."""
from __future__ import annotations

import os
from typing import Optional

from .base import StorageBackend, StorageError

_instance: Optional[StorageBackend] = None


def get_storage(force: bool = False) -> StorageBackend:
    global _instance
    if _instance is not None and not force:
        return _instance

    backend = os.getenv("STORAGE_BACKEND", "local").lower()
    if backend == "local":
        from .local import LocalStorage
        _instance = LocalStorage()
    elif backend in ("s3", "supabase"):
        from .s3 import S3Storage
        _instance = S3Storage()
    else:
        raise StorageError(f"Unknown STORAGE_BACKEND '{backend}' (use 'local' or 's3')")
    return _instance
