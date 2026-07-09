"""Heat scoring + Trending Now correlation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_heat_fresh_critical_kev_scores_high(make_article, secjournal):
    a = make_article(
        published=datetime.now(timezone.utc),
        severity="critical",
        kev=True,
        exploit=True,
        weight=2.0,
    )
    heat = secjournal.compute_heat(a)
    # fresh × critical × kev × exploit × 2.0 → > 15
    assert heat > 15, f"expected high heat, got {heat}"


def test_heat_old_low_severity_scores_low(make_article, secjournal):
    a = make_article(
        published=datetime.now(timezone.utc) - timedelta(days=7),
        severity="low",
    )
    heat = secjournal.compute_heat(a)
    assert 0 < heat < 0.2, f"expected low heat for 7-day-old low sev, got {heat}"


def test_heat_never_negative(make_article, secjournal):
    a = make_article(
        published=datetime.now(timezone.utc) + timedelta(days=1),  # future date
    )
    assert secjournal.compute_heat(a) > 0


def test_trending_multi_source_correlation(make_article, secjournal):
    """CVE cited by ≥ 2 sources gets promoted to Trending."""
    now = datetime.now(timezone.utc)
    by_theme = {
        "Trending": [],
        "CVE": [
            make_article(url="https://a.example/1", source="CVEFeed", cves=["CVE-2026-0001"], published=now),
            make_article(url="https://b.example/1", source="NVD",     cves=["CVE-2026-0001"], published=now),
            make_article(url="https://c.example/1", source="Krebs",   cves=["CVE-2099-9999"], published=now),
        ],
    }
    trending = secjournal.build_trending(by_theme, min_sources=2, top_k=10)
    urls = [a.url for a in trending]
    # both articles about CVE-2026-0001 should show up, the CVE-2099-9999 lone one shouldn't necessarily
    assert any("a.example" in u or "b.example" in u for u in urls), \
        "multi-source CVE didn't surface in trending"


def test_trending_fresh_kev_pinned(make_article, secjournal):
    """A KEV article published in the last 24h is pinned even if single-source."""
    now = datetime.now(timezone.utc)
    a = make_article(
        url="https://kev.example/x",
        source="CISA",
        kev=True,
        severity="critical",
        published=now - timedelta(hours=3),
    )
    trending = secjournal.build_trending({"Trending": [], "CVE": [a]}, min_sources=99, top_k=10)
    assert a in trending, "fresh KEV should be pinned to Trending"
