"""Validate the shipped feeds.yaml is well-formed and covers all themes."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT       = Path(__file__).resolve().parents[1]
FEEDS_YAML = ROOT / "configs" / "feeds.yaml"


@pytest.fixture(scope="module")
def feeds():
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(FEEDS_YAML.read_text(encoding="utf-8"))
    return data.get("feeds") or []


def test_feeds_file_present():
    assert FEEDS_YAML.is_file(), "configs/feeds.yaml missing"


def test_every_feed_has_required_fields(feeds):
    for f in feeds:
        for req in ("id", "label", "theme", "url"):
            assert f.get(req), f"feed {f} missing {req!r}"


def test_no_duplicate_ids(feeds):
    ids = [f["id"] for f in feeds]
    assert len(ids) == len(set(ids)), \
        f"duplicate feed IDs: {sorted(x for x in ids if ids.count(x) > 1)}"


def test_all_themes_covered(feeds):
    """Every documented theme must have at least one feed backing it."""
    documented = {"CVE", "Exploit", "Threat", "News-EN",
                  "News-FR", "News-CN", "Outils", "CTF"}
    present    = {f["theme"] for f in feeds}
    # Trending is computed not fetched, so it's absent by design
    missing    = documented - present
    assert not missing, f"themes with no feed: {missing}"


def test_urls_look_reasonable(feeds):
    """No obviously broken URL entries — must start with http(s)."""
    for f in feeds:
        assert f["url"].startswith(("http://", "https://")), \
            f"bad URL in feed {f['id']!r}: {f['url']!r}"


def test_weights_are_positive(feeds):
    for f in feeds:
        w = f.get("weight", 1.0)
        assert isinstance(w, (int, float)) and w > 0, \
            f"feed {f['id']!r} has invalid weight {w!r}"


def test_ftype_values_known(feeds):
    """Only recognised ftype markers are allowed."""
    known = {"rss", "json_kev", "gh_md"}
    for f in feeds:
        ftype = f.get("ftype", "rss")
        assert ftype in known, f"unknown ftype {ftype!r} on {f['id']!r}"


def test_no_localhost_or_private_endpoints(feeds):
    """Public repo policy — no personal infra in feed URLs."""
    forbidden = ("192.168.", "10.0.", "172.16.", "127.0.0.1", "localhost")
    for f in feeds:
        for token in forbidden:
            assert token not in f["url"], \
                f"feed {f['id']!r} points at private/personal infra: {f['url']!r}"
