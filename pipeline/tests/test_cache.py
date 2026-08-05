"""Tests for the content-addressed synthesis cache."""

import pytest
from pathlib import Path
from pipeline.cache import SynthesisCache


def test_store_and_lookup(tmp_path):
    cache = SynthesisCache(tmp_path)
    key = cache.store(
        text="Hello world",
        voice_hash="abc123",
        engine="edge-tts",
        config=None,
        result={"audio_path": "/tmp/hello.mp3", "duration": 2.5},
    )
    assert len(key) == 64  # SHA256 hex

    hit = cache.lookup(
        text="Hello world",
        voice_hash="abc123",
        engine="edge-tts",
        config=None,
    )
    assert hit is not None
    assert hit["result"]["audio_path"] == "/tmp/hello.mp3"


def test_miss(tmp_path):
    cache = SynthesisCache(tmp_path)
    hit = cache.lookup(
        text="Nonexistent",
        voice_hash="xyz",
        engine="edge-tts",
        config=None,
    )
    assert hit is None


def test_different_text_different_key(tmp_path):
    cache = SynthesisCache(tmp_path)
    k1 = cache.store("text A", "v1", "engine1", None, {"a": 1})
    k2 = cache.store("text B", "v1", "engine1", None, {"a": 1})
    assert k1 != k2


def test_persistence(tmp_path):
    cache1 = SynthesisCache(tmp_path)
    cache1.store("text", "v", "e", None, {"ok": True})

    cache2 = SynthesisCache(tmp_path)
    hit = cache2.lookup("text", "v", "e", None)
    assert hit is not None


def test_clear(tmp_path):
    cache = SynthesisCache(tmp_path)
    cache.store("a", "v", "e", None, {})
    cache.store("b", "v", "e", None, {})
    count = cache.clear()
    assert count == 2
    assert cache.size == 0


def test_size(tmp_path):
    cache = SynthesisCache(tmp_path)
    assert cache.size == 0
    cache.store("a", "v", "e", None, {})
    assert cache.size == 1
