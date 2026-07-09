"""Translation cache: same input → same output, no backend hit twice."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def test_cache_roundtrip(secjournal, tmp_path, monkeypatch):
    # Point the cache at a temp file, reset globals
    cache_path = tmp_path / "translation_cache.jsonl"
    monkeypatch.setattr(secjournal, "TRANSLATE_CACHE_PATH", cache_path)
    secjournal._TR_CACHE.clear()
    secjournal._TR_BACKEND = None

    # Force both backends to fail so we test the "no backend" branch
    monkeypatch.setattr(secjournal, "_try_ollama",
                        lambda t, timeout=20, target="en": None)
    monkeypatch.setattr(secjournal, "_try_deep_translator",
                        lambda t, target="en": None)

    out = secjournal.translate_to_en("Bonjour")
    assert out == "", "no backend must return empty string"


def test_cache_hit_avoids_backend_call(secjournal, tmp_path, monkeypatch):
    cache_path = tmp_path / "translation_cache.jsonl"
    monkeypatch.setattr(secjournal, "TRANSLATE_CACHE_PATH", cache_path)
    secjournal._TR_CACHE.clear()
    secjournal._TR_BACKEND = None

    calls = {"n": 0}
    def fake_backend(txt, timeout=20, target="en"):
        calls["n"] += 1
        return "Hello world"
    monkeypatch.setattr(secjournal, "_try_ollama", fake_backend)
    monkeypatch.setattr(secjournal, "_try_deep_translator",
                        lambda t, target="en": None)

    out1 = secjournal.translate_to_en("Bonjour le monde")
    out2 = secjournal.translate_to_en("Bonjour le monde")
    assert out1 == out2 == "Hello world"
    assert calls["n"] == 1, "cache didn't prevent the second backend call"


def test_cache_key_is_hash_of_input(secjournal, tmp_path, monkeypatch):
    cache_path = tmp_path / "translation_cache.jsonl"
    monkeypatch.setattr(secjournal, "TRANSLATE_CACHE_PATH", cache_path)
    secjournal._TR_CACHE.clear()
    secjournal._TR_BACKEND = None
    monkeypatch.setattr(secjournal, "_try_ollama",
                        lambda t, timeout=20, target="en": "OK")
    monkeypatch.setattr(secjournal, "_try_deep_translator",
                        lambda t, target="en": None)

    text = "unique fragment 42"
    secjournal.translate_to_en(text)
    # Cache key includes target language prefix (translate_to_en → target="en")
    expected_key = hashlib.md5(("en" + "\x00" + text).encode()).hexdigest()
    assert expected_key in secjournal._TR_CACHE
    assert secjournal._TR_CACHE[expected_key] == "OK"


def test_cache_survives_reload(secjournal, tmp_path, monkeypatch):
    cache_path = tmp_path / "translation_cache.jsonl"
    monkeypatch.setattr(secjournal, "TRANSLATE_CACHE_PATH", cache_path)
    secjournal._TR_CACHE.clear()
    secjournal._TR_BACKEND = None
    monkeypatch.setattr(secjournal, "_try_ollama",
                        lambda t, timeout=20, target="en": "persisted!")
    monkeypatch.setattr(secjournal, "_try_deep_translator",
                        lambda t, target="en": None)

    secjournal.translate_to_en("keep me around")
    secjournal._save_translation_cache()
    assert cache_path.is_file()

    # simulate a new process by wiping the in-memory cache then loading
    secjournal._TR_CACHE.clear()
    secjournal._load_translation_cache()
    assert any(v == "persisted!" for v in secjournal._TR_CACHE.values())
