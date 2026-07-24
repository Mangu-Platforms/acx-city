"""Local storage backend: put/get/exists/delete, signed-URL issuance and
verification, expiry, and path-traversal protection."""
import tempfile
import time

import pytest

from storage.base import StorageError
from storage.local import LocalStorage


@pytest.fixture()
def store():
    root = tempfile.mkdtemp(prefix="stor_")
    return LocalStorage(root=root, secret="unit-secret")


def test_put_get_exists_delete(store):
    key = "org/1/jobs/9/audiobook.mp3"
    assert not store.exists(key)
    store.put_bytes(key, b"ID3data", "audio/mpeg")
    assert store.exists(key)
    assert store.get_bytes(key) == b"ID3data"
    store.delete(key)
    assert not store.exists(key)


def test_get_missing_raises(store):
    with pytest.raises(StorageError):
        store.get_bytes("nope/missing.mp3")


def test_signed_url_roundtrip(store):
    key = "org/1/jobs/9/audiobook.mp3"
    store.put_bytes(key, b"x")
    signed = store.signed_url(key, expires_in=60, download_name="book.mp3")
    assert key in signed.url and "sig=" in signed.url and signed.expires_in == 60

    # Parse and verify the token.
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(signed.url).query)
    expires = int(q["expires"][0])
    sig = q["sig"][0]
    assert store.verify(key, expires, sig) is True
    assert store.verify(key, expires, "tampered") is False


def test_signed_url_expiry(store):
    key = "org/1/f.mp3"
    store.put_bytes(key, b"x")
    # A signature for a past expiry must not verify.
    past = int(time.time()) - 5
    assert store.verify(key, past, store.sign(key, past)) is False


def test_path_traversal_blocked(store):
    with pytest.raises(StorageError):
        store.put_bytes("../../etc/evil", b"x")


def test_signed_url_missing_object(store):
    with pytest.raises(StorageError):
        store.signed_url("does/not/exist.mp3")


def test_factory_selects_local(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", tempfile.mkdtemp(prefix="fac_"))
    from storage.factory import get_storage
    s = get_storage(force=True)
    assert type(s).__name__ == "LocalStorage"
