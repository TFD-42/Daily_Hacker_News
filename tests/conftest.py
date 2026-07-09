"""Pytest fixtures shared across the whole suite.

Two roles:
  1. Load `scripts/secjournal.py` under the module name `secjournal` so tests
     can `import secjournal` without a package rename dance.
  2. Provide small helpers for building fake `Article` objects and driving the
     hardened HTTP server without hitting the network.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT       = Path(__file__).resolve().parents[1]
SCRIPTS    = ROOT / "scripts"


def _load(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def secjournal():
    return _load("secjournal", SCRIPTS / "secjournal.py")


@pytest.fixture(scope="session")
def serve_mod():
    return _load("serve", SCRIPTS / "serve.py")


@pytest.fixture(scope="session")
def search_external():
    return _load("search_external", SCRIPTS / "search_external.py")


@pytest.fixture
def make_article(secjournal):
    """Factory returning `secjournal.Article` with sensible defaults."""
    def _mk(**kw):
        defaults = dict(
            title="A demo advisory",
            url="https://example.com/a",
            source="Example",
            theme="CVE",
            published=datetime.now(timezone.utc),
        )
        defaults.update(kw)
        return secjournal.Article(**defaults)
    return _mk


@pytest.fixture
def tmp_journal_dir(tmp_path):
    """Fake `out/journals` structure with one HTML journal + feed.json."""
    d = tmp_path / "out" / "journals"
    d.mkdir(parents=True)
    (d / "secjournal_20260101_0000.html").write_text(
        "<!doctype html><html><body>demo</body></html>", encoding="utf-8"
    )
    (d / "feed.json").write_text('{"items": []}', encoding="utf-8")
    (d / "secjournal_feeds.opml").write_text('<?xml version="1.0"?><opml/>', encoding="utf-8")
    return d
