"""Storage backend contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class StorageError(Exception):
    """Raised for backend failures (upload, signing, missing object)."""


@dataclass
class SignedURL:
    url: str
    expires_in: int  # seconds


class StorageBackend(ABC):
    """Object storage over opaque keys.

    Keys are POSIX-style paths, e.g. ``org/<org_id>/jobs/<job_id>/audiobook.mp3``.
    Implementations must be safe to construct without network access; failures
    surface only when a method is actually called.
    """

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store bytes at key. Returns the key."""

    @abstractmethod
    def put_file(self, key: str, local_path: str, content_type: str = "application/octet-stream") -> str:
        """Upload a local file to key. Returns the key."""

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        """Fetch the object's bytes. Raises StorageError if missing."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        ...

    @abstractmethod
    def signed_url(self, key: str, expires_in: int = 3600, download_name: Optional[str] = None) -> SignedURL:
        """Return a time-limited URL that grants direct read access to key.

        This is what the API hands to clients instead of streaming bytes through
        the app, and it means download authorization is scoped and expiring.
        """
