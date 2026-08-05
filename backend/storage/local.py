"""Local-filesystem storage backend for dev / sandbox / tests.

Signed URLs point at an app route (``/api/files/<key>?...``) protected by an
HMAC token with an expiry, so the client-side download flow is identical to the
cloud path — no bytes streamed through business-logic endpoints, and links
expire — without needing any cloud credentials.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional
from urllib.parse import quote

from utils.runtime_env import is_production

from .base import SignedURL, StorageBackend, StorageError


class LocalStorage(StorageBackend):
    def __init__(self, root: Optional[str] = None, secret: Optional[str] = None, public_base: str = ""):
        self.root = root or os.getenv("STORAGE_LOCAL_ROOT", "storage_data")
        # Signing secret; falls back to JWT_SECRET, then a dev-only default —
        # in production a guessable signing secret means forgeable download
        # links, so refuse to start without a real one.
        self.secret = secret or os.getenv("STORAGE_SIGNING_SECRET") or os.getenv("JWT_SECRET") or ""
        if not self.secret:
            if is_production():
                raise StorageError(
                    "STORAGE_SIGNING_SECRET (or JWT_SECRET) must be set in "
                    "production — signed download URLs would be forgeable."
                )
            self.secret = "dev-insecure-secret-change-me"
        # Prefix for generated URLs; empty = same-origin relative path.
        self.public_base = public_base or os.getenv("PUBLIC_BASE_URL", "")
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        # Prevent path traversal; keys are normalized POSIX paths.
        safe = os.path.normpath(key).lstrip("/")
        if safe.startswith(".."):
            raise StorageError(f"Invalid key: {key}")
        return os.path.join(self.root, safe)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return key

    def put_file(self, key: str, local_path: str, content_type: str = "application/octet-stream") -> str:
        with open(local_path, "rb") as f:
            return self.put_bytes(key, f.read(), content_type)

    def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not os.path.exists(path):
            raise StorageError(f"Object not found: {key}")
        with open(path, "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass

    # --- signed access -----------------------------------------------------
    def sign(self, key: str, expires_at: int) -> str:
        msg = f"{key}:{expires_at}".encode()
        return hmac.new(self.secret.encode(), msg, hashlib.sha256).hexdigest()

    def verify(self, key: str, expires_at: int, signature: str) -> bool:
        if expires_at < int(time.time()):
            return False
        expected = self.sign(key, expires_at)
        return hmac.compare_digest(expected, signature)

    def signed_url(self, key: str, expires_in: int = 3600, download_name: Optional[str] = None) -> SignedURL:
        if not self.exists(key):
            raise StorageError(f"Object not found: {key}")
        expires_at = int(time.time()) + expires_in
        sig = self.sign(key, expires_at)
        params = f"expires={expires_at}&sig={sig}"
        if download_name:
            params += f"&name={quote(download_name)}"
        url = f"{self.public_base}/api/files/{quote(key)}?{params}"
        return SignedURL(url=url, expires_in=expires_in)
