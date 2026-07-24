"""Pluggable object storage.

Manuscripts and rendered audio are stored as opaque keys, not local paths, so the
same code works against local disk (dev/sandbox/tests) or Supabase Storage / any
S3-compatible service (production), selected by the STORAGE_BACKEND env var.

    STORAGE_BACKEND=local     -> LocalStorage (default)
    STORAGE_BACKEND=s3        -> S3Storage (works with Supabase's S3 gateway,
                                 MinIO, Cloudflare R2, AWS S3)
"""
from .base import SignedURL, StorageBackend, StorageError
from .factory import get_storage

__all__ = ["StorageBackend", "SignedURL", "StorageError", "get_storage"]
