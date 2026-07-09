#!/usr/bin/env python3
"""
secjournal.py — Daily Hacker News, journal de veille sécurité / pentest
Agrège RSS feeds + items rss_watcher → journal structuré HTML + Markdown

Usage :
    python3 scripts/secjournal.py                    # journal 1 jour, HTML
    python3 scripts/secjournal.py --days 7           # 7 derniers jours
    python3 scripts/secjournal.py --output both      # HTML + Markdown
    python3 scripts/secjournal.py --output md        # Markdown seul
    python3 scripts/secjournal.py --themes CVE,Exploit
    python3 scripts/secjournal.py --max 30           # max articles/thème
    python3 scripts/secjournal.py --open             # ouvre le HTML auto
    python3 scripts/secjournal.py --export-opml      # exporte OPML

Requirements : pip install feedparser (stdlib only sinon)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ── Résolution des chemins ────────────────────────────────────────────────────
# Objectif : pouvoir modifier sources / configs / knowledge SANS recompiler.
# Frozen (.app) : on lit en priorité le dossier PROJET externe (éditable) ;
# les données embarquées dans le binaire ne servent que de repli.

def _project_root() -> Optional[Path]:
    """Dossier projet éditable (contient configs/ + scripts/), s'il existe."""
    if getattr(sys, "frozen", False):
        # …/DailyHackerNews.app/Contents/MacOS/DailyHackerNews_bin → on remonte les parents
        for p in Path(sys.executable).resolve().parents:
            if (p / "configs").is_dir() and (p / "scripts").is_dir():
                return p
        return None
    return Path(__file__).resolve().parents[1]

PROJECT_ROOT = _project_root()
_MEIPASS     = getattr(sys, "_MEIPASS", None)
BUNDLE_ROOT  = Path(_MEIPASS) if _MEIPASS else None

# Lecture des données : projet éditable > données embarquées > dossier exécutable
DATA_ROOT = PROJECT_ROOT or BUNDLE_ROOT or Path(sys.executable).resolve().parent
# Écriture : projet éditable si dispo, sinon ~/DailyHackerNews (bundle en lecture seule)
OUT_BASE  = PROJECT_ROOT or (Path.home() / "DailyHackerNews")

# Compat : plusieurs modules réfèrent encore ROOT
ROOT       = DATA_ROOT
CONFIG_DIR = DATA_ROOT / "configs"
OUT_DIR    = OUT_BASE / "out" / "journals"
# SITE_DIR is the ONLY directory the web server is allowed to expose. Every
# publicly servable artifact (HTML, feed.json, OPML) is written here; internal
# outputs (Markdown, caches, the store) stay in OUT_DIR / knowledge and are
# therefore physically out of the server's reach.
SITE_DIR   = OUT_DIR / "site"
KB_RSS     = DATA_ROOT / "knowledge" / "rss" / "items.jsonl"
STORE      = OUT_BASE / "knowledge" / "rss" / "journal_store.jsonl"
STORE_CAP  = 5000
OUT_DIR.mkdir(parents=True, exist_ok=True)
SITE_DIR.mkdir(parents=True, exist_ok=True)

UA = "DailyHackerNews/1.0"

try:
    import feedparser as _feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

# ══════════════════════════════════════════════════════════════════════════════
# SOURCES (étendues vs rss_watcher.py)
# ══════════════════════════════════════════════════════════════════════════════

_BUILTIN_FEEDS: list[dict] = [
    # ── CVE & Vulnérabilités ─────────────────────────────────────────────────
    dict(id="nvd-rss",        label="NVD (NIST)",          theme="CVE",
         url="https://nvd.nist.gov/feeds/xml/cve/misc/nvd-rss.xml"),
    dict(id="cvefeed-high",   label="CVEFeed HIGH/CRIT",   theme="CVE",
         url="https://cvefeed.io/rssfeed/severity/high.xml"),
    dict(id="cvefeed-latest", label="CVEFeed Latest",      theme="CVE",
         url="https://cvefeed.io/rssfeed/latest.xml"),
    dict(id="cvealert",       label="CVE Alert",           theme="CVE",
         url="https://cvealert.net/feeds/rss2/"),
    dict(id="cert-fr",        label="CERT-FR (ANSSI)",     theme="CVE",
         url="https://www.cert.ssi.gouv.fr/feed/"),
    dict(id="cisa-kev",       label="CISA KEV",            theme="CVE",
         url="https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
         ftype="json_kev"),
    dict(id="opencve",        label="OpenCVE",             theme="CVE",
         url="https://www.opencve.io/cve?format=rss"),
    dict(id="cvedetails",     label="CVEDetails",          theme="CVE",
         url="https://www.cvedetails.com/feeds/latest/"),

    # ── Exploits & PoC ───────────────────────────────────────────────────────
    dict(id="exploitdb",      label="Exploit-DB",          theme="Exploit",
         url="https://www.exploit-db.com/rss.xml"),
    dict(id="packetstorm",    label="Packet Storm",        theme="Exploit",
         url="https://packetstormsecurity.com/feeds"),
    dict(id="full-disc",      label="Full Disclosure",     theme="Exploit",
         url="https://seclists.org/rss/fulldisclosure.rss"),
    dict(id="sploitus",       label="Sploitus",            theme="Exploit",
         url="https://sploitus.com/feeds/"),
    dict(id="trickest-cve",   label="Trickest CVE PoC",   theme="Exploit",
         url="https://raw.githubusercontent.com/trickest/cve/main/README.md",
         ftype="gh_md"),
    dict(id="vulhub",         label="Vulhub PoC",         theme="Exploit",
         url="https://raw.githubusercontent.com/vulhub/vulhub/master/README.md",
         ftype="gh_md"),

    # ── Security News EN ─────────────────────────────────────────────────────
    dict(id="krebs",          label="Krebs on Security",   theme="News-EN",
         url="https://krebsonsecurity.com/feed/"),
    dict(id="hackernews",     label="The Hacker News",     theme="News-EN",
         url="https://feeds.feedburner.com/TheHackersNews"),
    dict(id="bleeping",       label="Bleeping Computer",   theme="News-EN",
         url="https://www.bleepingcomputer.com/feed/"),
    dict(id="rapid7",         label="Rapid7 Blog",         theme="News-EN",
         url="https://www.rapid7.com/blog/rss/"),
    dict(id="portswigger",    label="PortSwigger Daily",   theme="News-EN",
         url="https://portswigger.net/daily-swig/rss"),
    dict(id="schneier",       label="Schneier on Security",theme="News-EN",
         url="https://www.schneier.com/feed/atom/"),
    dict(id="darkreading",    label="Dark Reading",        theme="News-EN",
         url="https://www.darkreading.com/rss.xml"),
    dict(id="sans-isc",       label="SANS ISC Diary",      theme="News-EN",
         url="https://isc.sans.edu/rssfeed.xml"),
    dict(id="securityweek",   label="SecurityWeek",        theme="News-EN",
         url="https://www.securityweek.com/feed/"),
    dict(id="threatpost",     label="Threatpost",          theme="News-EN",
         url="https://threatpost.com/feed/"),
    dict(id="specterops",     label="SpecterOps",          theme="News-EN",
         url="https://posts.specterops.io/feed"),

    # ── Actualités FR ────────────────────────────────────────────────────────
    dict(id="zataz",          label="ZATAZ",               theme="News-FR",
         url="https://www.zataz.com/feed/"),
    dict(id="korben",         label="Korben",              theme="News-FR",
         url="https://korben.info/feed"),
    dict(id="it-connect",     label="IT-Connect Sécurité", theme="News-FR",
         url="https://www.it-connect.fr/category/securite/feed/"),
    dict(id="lemagit",        label="LeMagIT Sécurité",   theme="News-FR",
         url="https://www.lemagit.fr/rss/Securite"),

    # ── Outils & Techniques ──────────────────────────────────────────────────
    dict(id="hackingarticles",label="Hacking Articles",   theme="Outils",
         url="https://www.hackingarticles.in/feed/"),
    dict(id="pentestlab",     label="Pentestlab Blog",     theme="Outils",
         url="https://pentestlab.blog/feed/"),
    dict(id="harmj0y",        label="harmj0y",             theme="Outils",
         url="https://blog.harmj0y.net/feed/"),
    dict(id="offsec",         label="OffSec Blog",         theme="Outils",
         url="https://www.offensive-security.com/feed/"),
    dict(id="0xdf",           label="0xdf Writeups",       theme="CTF",
         url="https://0xdf.gitlab.io/feed.xml"),

    # ── CTF & Labs ───────────────────────────────────────────────────────────
    dict(id="ctftime",        label="CTFtime Events",      theme="CTF",
         url="https://ctftime.org/event/list/upcoming/rss/"),
    dict(id="root-me",        label="Root-Me",             theme="CTF",
         url="https://www.root-me.org/spip.php?page=backend"),
]


def load_feeds() -> list[dict]:
    """Charge les sources depuis configs/feeds.yaml (éditable → aucune
    recompilation nécessaire pour ajouter/retirer un flux). Repli sur la liste
    intégrée si le fichier est absent, illisible, ou PyYAML indisponible."""
    fp = CONFIG_DIR / "feeds.yaml"
    if fp.is_file():
        try:
            import yaml
            data  = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
            feeds = data.get("feeds") or []
            norm  = [
                f for f in feeds
                if f.get("id") and f.get("url") and f.get("theme")
                and f.get("enabled", True) is not False
            ]
            if norm:
                return norm
            print(f"[!] {fp.name} empty/invalid — using built-in feed list", file=sys.stderr)
        except Exception as e:
            print(f"[!] {fp.name} ignored ({e}) — using built-in feed list", file=sys.stderr)
    return _BUILTIN_FEEDS


ALL_FEEDS: list[dict] = load_feeds()

THEMES: dict[str, dict] = {
    "Trending":{"icon": "🔥", "title": "Trending Now (multi-source)","color": "#ff4757", "bg": "#2c0808"},
    "CVE":     {"icon": "🔴", "title": "CVE & Vulnerabilities",     "color": "#e74c3c", "bg": "#2c0f0f"},
    "Threat":  {"icon": "🎯", "title": "Threat Intelligence",       "color": "#f39c12", "bg": "#2c1f08"},
    "Exploit": {"icon": "💥", "title": "Exploits & PoC",            "color": "#e67e22", "bg": "#2c1a08"},
    "News-EN": {"icon": "🌐", "title": "Security News (EN)",        "color": "#3498db", "bg": "#0a1a2c"},
    "News-FR": {"icon": "🇫🇷", "title": "Security News (FR-origin)","color": "#2ecc71", "bg": "#0a2c10"},
    "News-CN": {"icon": "🇨🇳", "title": "Security News (CN-origin)","color": "#e91e63", "bg": "#2c0a1e"},
    "Outils":  {"icon": "🛠",  "title": "Tools & Techniques",        "color": "#9b59b6", "bg": "#1a0a2c"},
    "CTF":     {"icon": "🏁", "title": "CTF & Labs",                "color": "#1abc9c", "bg": "#082c28"},
}

# Default source language per theme. Non-English themes get their titles and
# summaries auto-translated to English so the whole journal reads in English.
THEME_LANG = {"News-FR": "fr", "News-CN": "zh"}

# Trending is computed, not fetched: it appears at the top of the journal when
# multi-source articles overlap on the same CVE within the time window.
THEME_ORDER = ["Trending", "CVE", "Threat", "Exploit", "News-EN", "News-FR", "News-CN", "Outils", "CTF"]

# ══════════════════════════════════════════════════════════════════════════════
# DATA MODEL
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Article:
    title:     str
    url:       str
    source:    str
    theme:     str
    published: datetime
    summary:   str      = ""
    tags:      list     = field(default_factory=list)
    cves:      list     = field(default_factory=list)
    severity:  str      = ""
    kev:       bool     = False
    exploit:   bool     = False
    score:     int      = 0
    cmd:       str      = ""
    summary_fr:str      = ""
    summary_en:str      = ""   # English translation of the summary (auto, best-effort)
    title_en:  str      = ""   # English translation of the title (auto, best-effort)
    lang:      str      = "en" # source language (ISO 639-1); drives translation
    weight:    float    = 1.0  # source multiplier (>1 = premium)
    heat:      float    = 0.0  # freshness / severity / KEV score (filled later)

    @property
    def uid(self) -> str:
        return hashlib.md5(self.url.encode(), usedforsecurity=False).hexdigest()[:10]

    @property
    def age_str(self) -> str:
        now = datetime.now(timezone.utc)
        delta = now - self.published
        h = int(delta.total_seconds() / 3600)
        if h < 1:
            return "just now"
        if h < 24:
            return f"{h}h ago"
        return f"{delta.days}d ago"

    @property
    def date_fmt(self) -> str:
        return self.published.strftime("%d/%m %H:%M")

# ══════════════════════════════════════════════════════════════════════════════
# HTTP + PARSERS
# ══════════════════════════════════════════════════════════════════════════════

def http_get(url: str, timeout: int = 18) -> Optional[bytes]:
    """Simple bytes fetch. Kept for callers that don't want diagnostics."""
    body, _ = http_get_verbose(url, timeout=timeout)
    return body


def http_get_verbose(url: str, timeout: int = 18) -> tuple[Optional[bytes], str]:
    """Fetch + return (body, diag_string). diag empty on success."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA,
              "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            ct   = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
            # HTML page returned when we asked for a feed = dead / redirected
            if ct.startswith("text/html") and b"<rss" not in body[:512] and b"<feed" not in body[:512]:
                return body, f"HTML at feed URL ({ct})"
            return body, ""
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"URL: {getattr(e, 'reason', e)}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:60]}"


def _parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fn in (
        lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")),
        lambda x: parsedate_to_datetime(x),
        lambda x: datetime.strptime(x[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc),
    ):
        try:
            dt = fn(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None


def _strip_tags(text: str, maxlen: int = 350) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:maxlen] + "…" if len(text) > maxlen else text


def _parse_rss_stdlib(raw: bytes, label: str, theme: str, cutoff: datetime) -> list[Article]:
    """Parse RSS/Atom avec xml.etree (fallback sans feedparser)."""
    import xml.etree.ElementTree as ET
    arts: list[Article] = []
    try:
        root = ET.fromstring(raw)
        ATOM = "http://www.w3.org/2005/Atom"
        entries = (root.findall(f"{{{ATOM}}}entry") or
                   root.findall(".//item"))
        for e in entries:
            def txt(*tags):
                for t in tags:
                    v = e.findtext(t) or e.findtext(f"{{{ATOM}}}{t}")
                    if v: return v.strip()
                return ""
            title   = txt("title") or "Sans titre"
            link_el = e.find("link") or e.find(f"{{{ATOM}}}link")
            link    = (link_el.text or link_el.get("href","")).strip() if link_el is not None else ""
            desc    = txt("description","summary","content")
            pub_str = txt("pubDate","published","updated","dc:date")
            pub     = _parse_date(pub_str) or datetime.now(timezone.utc)
            if pub < cutoff:
                continue
            cves = list(set(re.findall(r"CVE-\d{4}-\d{4,}", title + " " + desc, re.I)))
            arts.append(Article(
                title=title[:200], url=link, source=label, theme=theme,
                published=pub, summary=_strip_tags(desc), cves=cves,
            ))
    except Exception:
        pass
    return arts


def _parse_rss_feedparser(raw: bytes, label: str, theme: str, cutoff: datetime) -> list[Article]:
    arts: list[Article] = []
    try:
        feed = _feedparser.parse(raw)
        for e in feed.entries:
            pub = None
            for attr in ("published", "updated", "created"):
                v = getattr(e, attr, None)
                if v:
                    pub = _parse_date(v)
                    if pub:
                        break
            if pub is None:
                pub = datetime.now(timezone.utc)
            if pub < cutoff:
                continue
            title   = getattr(e, "title", "Sans titre")[:200]
            url     = getattr(e, "link", "")
            summary = _strip_tags(getattr(e, "summary", "") or getattr(e, "description", ""))
            tags    = [t.term for t in getattr(e, "tags", []) if hasattr(t, "term")]
            cves    = list(set(re.findall(r"CVE-\d{4}-\d{4,}", title + " " + summary, re.I)))
            arts.append(Article(
                title=title, url=url, source=label, theme=theme,
                published=pub, summary=summary, tags=tags, cves=cves,
            ))
    except Exception:
        pass
    return arts


def parse_rss(raw: bytes, label: str, theme: str, cutoff: datetime) -> list[Article]:
    if HAS_FEEDPARSER:
        return _parse_rss_feedparser(raw, label, theme, cutoff)
    return _parse_rss_stdlib(raw, label, theme, cutoff)


def parse_kev_json(raw: bytes, label: str, cutoff: datetime) -> list[Article]:
    arts: list[Article] = []
    try:
        data  = json.loads(raw)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for v in data.get("vulnerabilities", []):
            date_str = v.get("dateAdded", today)
            pub = _parse_date(date_str) or datetime.now(timezone.utc)
            if pub < cutoff:
                continue
            cve  = v.get("cveID", "")
            name = v.get("vulnerabilityName", "")
            desc = v.get("shortDescription", "")
            arts.append(Article(
                title     = f"{cve} — {name}"[:200],
                url       = f"https://nvd.nist.gov/vuln/detail/{cve}",
                source    = label, theme="CVE", published=pub,
                summary   = desc, cves=[cve], kev=True,
                severity  = "critical",
                tags      = ["KEV", "exploited-in-wild"],
            ))
    except Exception:
        pass
    return arts


def parse_gh_md(raw: bytes, label: str, theme: str) -> list[Article]:
    """Extrait les CVEs listés dans un README GitHub."""
    arts: list[Article] = []
    text = raw.decode("utf-8", errors="ignore")
    blocks = re.findall(
        r"(CVE-\d{4}-\d{4,}[^\n]*(?:\n(?!CVE-)[^\n]+){0,4})", text
    )
    for block in blocks[:80]:
        cve_ids = re.findall(r"CVE-\d{4}-\d{4,}", block)
        links   = re.findall(r"https?://\S+", block)
        cve_id  = cve_ids[0] if cve_ids else "?"
        link    = links[0].rstrip(").,") if links else f"https://github.com/topics/cve"
        arts.append(Article(
            title     = f"{cve_id} — PoC disponible",
            url       = link,
            source    = label, theme=theme,
            published = datetime.now(timezone.utc),
            summary   = _strip_tags(block),
            cves      = cve_ids[:3],
            tags      = ["PoC", "GitHub"],
        ))
    return arts


# ── Fetch one feed ────────────────────────────────────────────────────────────

def fetch_feed(feed: dict, cutoff: datetime) -> list[Article]:
    """Backward-compat wrapper: returns list of Article only."""
    arts, _ = fetch_feed_verbose(feed, cutoff)
    return arts


def fetch_feed_verbose(feed: dict, cutoff: datetime) -> tuple[list[Article], str]:
    """Fetch one feed and return (articles, diag). diag is empty on success,
    otherwise carries the HTTP status / parse issue for the summary line."""
    raw, diag = http_get_verbose(feed["url"])
    if raw is None:
        return [], diag or "no body"
    ftype = feed.get("ftype", "rss")
    if ftype == "json_kev":
        arts = parse_kev_json(raw, feed["label"], cutoff)
    elif ftype == "gh_md":
        arts = parse_gh_md(raw, feed["label"], feed["theme"])
    else:
        arts = parse_rss(raw, feed["label"], feed["theme"], cutoff)
    w    = float(feed.get("weight", 1.0))
    lang = feed.get("lang") or THEME_LANG.get(feed["theme"], "en")
    for a in arts:
        a.weight = w
        a.lang   = lang
    if not arts and not diag:
        diag = "parsed 0 items (feed empty or out of window)"
    return arts, diag


def verify_feeds(feeds: list[dict], workers: int = 12) -> list[dict]:
    """Probe every feed URL and return a status list. Diagnostic for the
    --verify-feeds mode: shows which sources actually respond."""
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)  # wide window
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_feed_verbose, f, cutoff): f for f in feeds}
        for fut in as_completed(futs):
            f = futs[fut]
            try:
                arts, diag = fut.result()
            except Exception as e:
                arts, diag = [], f"exception: {e}"
            out.append({
                "id":       f.get("id"),
                "label":    f.get("label"),
                "theme":    f.get("theme"),
                "url":      f.get("url"),
                "articles": len(arts),
                "status":   "ok" if arts else ("dead" if diag and "HTTP" in diag or "URL:" in diag else "quiet"),
                "diag":     diag or "",
            })
    return out


# ── Load rss_watcher items (Ollama-enriched) ─────────────────────────────────

def load_rss_watcher_items(cutoff: datetime) -> list[Article]:
    arts: list[Article] = []
    if not KB_RSS.exists():
        return arts
    CAT_TO_THEME = {
        "cve": "CVE", "poc": "Exploit", "exploit": "Exploit",
        "advisory": "CVE", "news": "News-EN",
    }
    for line in KB_RSS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item  = json.loads(line)
            pub   = _parse_date(item.get("pubdate", "")) or datetime.now(timezone.utc)
            if pub < cutoff:
                continue
            ol    = item.get("ollama", {})
            theme = CAT_TO_THEME.get(item.get("cat", ""), "News-EN")
            sfr   = ol.get("summary_fr", "")
            if isinstance(sfr, dict):
                # certains items Ollama stockent {"fr": "...", ...} au lieu d'un str
                sfr = sfr.get("fr") or next(iter(sfr.values()), "") or ""
            elif not isinstance(sfr, str):
                sfr = str(sfr)
            arts.append(Article(
                title      = item.get("title", "")[:200],
                url        = item.get("link", ""),
                source     = item.get("feed_id", "rss_watcher").replace("-", " ").title(),
                theme      = theme,
                published  = pub,
                summary    = item.get("summary", ""),
                cves       = item.get("cves", []),
                kev        = item.get("kev", False),
                severity   = ol.get("severity", ""),
                exploit    = bool(ol.get("exploit_available")),
                score      = int(ol.get("pentest_relevance", 0) or 0),
                cmd        = ol.get("exploit_cmd", ""),
                summary_fr = sfr,
                tags       = ol.get("tags", []),
            ))
        except Exception:
            pass
    return arts


# ══════════════════════════════════════════════════════════════════════════════
# HEAT SCORE + TRENDING (cross-source correlation)
# ══════════════════════════════════════════════════════════════════════════════

def compute_heat(art: Article) -> float:
    """Score de chaleur : fraicheur * severite * KEV * exploit * poids source.

    Un article publie il y a 1h avec KEV/critical exploite pesera >> qu'un
    article de 5 jours sans severite. Utilise pour promouvoir le "gold now".
    """
    now   = datetime.now(timezone.utc)
    hours = max(0.5, (now - art.published).total_seconds() / 3600.0)
    fresh = 1.0 / (1.0 + hours / 12.0)     # 1.0 @ 0h · ~0.5 @ 12h · ~0.15 @ 72h
    sev   = {"critical": 2.5, "high": 1.8, "medium": 1.2, "low": 0.7}.get(
        (art.severity or "").lower(), 1.0)
    kev   = 2.2 if art.kev else 1.0
    expl  = 1.6 if art.exploit else 1.0
    return round(fresh * sev * kev * expl * float(art.weight or 1.0), 3)


def build_trending(by_theme: dict, min_sources: int = 2, top_k: int = 30) -> list[Article]:
    """Detecte les articles trending :
      1. CVEs mentionnees par >= min_sources feeds distincts dans la fenetre.
      2. Articles KEV publies dans les 24 dernieres heures.
      3. Top heat_score parmi les 24h les plus recentes.
    Retourne une liste dedupliquee, triee par heat_score decroissant."""
    all_arts: list[Article] = [a for arts in by_theme.values() for a in arts]
    if not all_arts:
        return []

    # 1. CVE -> {sources}
    cve_sources: dict[str, set[str]] = {}
    cve_arts:    dict[str, list[Article]] = {}
    for a in all_arts:
        for cve in (a.cves or []):
            cve = cve.upper()
            cve_sources.setdefault(cve, set()).add(a.source)
            cve_arts.setdefault(cve, []).append(a)
    hot_cves = {c for c, s in cve_sources.items() if len(s) >= min_sources}

    now = datetime.now(timezone.utc)
    trending: dict[str, Article] = {}   # uid -> article

    # 1a. CVEs multi-source
    for cve in hot_cves:
        # garder l'article le plus "chaud" pour la CVE
        best = max(cve_arts[cve], key=compute_heat)
        trending[best.uid] = best

    # 2. KEV frais (< 24h)
    for a in all_arts:
        if a.kev and (now - a.published).total_seconds() < 86400:
            trending[a.uid] = a

    # 3. top-heat parmi les < 24h
    fresh = [a for a in all_arts if (now - a.published).total_seconds() < 86400]
    fresh.sort(key=compute_heat, reverse=True)
    for a in fresh[:top_k]:
        trending.setdefault(a.uid, a)

    out = list(trending.values())
    out.sort(key=compute_heat, reverse=True)
    return out[:top_k]


# ══════════════════════════════════════════════════════════════════════════════
# TRANSLATION EN — backend stack : Ollama > deep_translator > passthrough
# ══════════════════════════════════════════════════════════════════════════════

TRANSLATE_CACHE_PATH = OUT_BASE / "knowledge" / "rss" / "translation_cache.jsonl"
_TR_CACHE: dict[str, str] = {}
_TR_BACKEND: Optional[str] = None   # rempli au premier appel


def _load_translation_cache() -> None:
    global _TR_CACHE
    if _TR_CACHE:
        return
    if TRANSLATE_CACHE_PATH.is_file():
        try:
            for line in TRANSLATE_CACHE_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("k") and r.get("v"):
                    _TR_CACHE[r["k"]] = r["v"]
        except Exception:
            pass


def _save_translation_cache() -> None:
    if not _TR_CACHE:
        return
    try:
        TRANSLATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TRANSLATE_CACHE_PATH.open("w", encoding="utf-8") as f:
            for k, v in _TR_CACHE.items():
                f.write(json.dumps({"k": k, "v": v}, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[!] translation cache not written ({e})", file=sys.stderr)


def _ollama_host() -> str:
    import os
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _ollama_model() -> str:
    import os
    return os.environ.get("OLLAMA_TRANSLATE_MODEL", "qwen2.5:3b")


def _ollama_daemon_up(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(_ollama_host() + "/api/tags", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _ollama_model_present(model: str) -> bool:
    try:
        with urllib.request.urlopen(_ollama_host() + "/api/tags", timeout=3) as r:
            data = json.loads(r.read())
    except Exception:
        return False
    want = model.split(":")[0].lower()
    for m in data.get("models", []):
        name = (m.get("name") or "").split(":")[0].lower()
        if name == want:
            return True
    return False


def _which(binary: str) -> Optional[str]:
    import shutil
    return shutil.which(binary)


def _prompt_yes(question: str, auto: bool = False) -> bool:
    if auto:
        return True
    if not sys.stdin.isatty():
        return False  # non-interactif : on n'installe rien sans consentement
    try:
        r = input(f"  {question} [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return r in ("", "y", "yes", "o", "oui")


def _install_ollama() -> bool:
    """Installe Ollama via le script officiel (macOS/Linux) ou pointe vers
    la page de telechargement (Windows). Bloque jusqu'a fin d'install."""
    import platform
    system = platform.system()
    print(f"  {c('cyan','⇩')} installation d'Ollama pour {system}…")
    if system in ("Darwin", "Linux"):
        # brew si dispo sur macOS, sinon script officiel
        if system == "Darwin" and _which("brew"):
            r = subprocess.run(["brew", "install", "ollama"])
            return r.returncode == 0
        r = subprocess.run("curl -fsSL https://ollama.com/install.sh | sh",
                           shell=True)
        return r.returncode == 0
    if system == "Windows":
        print("  Windows : telechargez depuis https://ollama.com/download/windows")
        print("           puis relancez la commande.")
        return False
    print(f"  OS non gere ({system})")
    return False


def _start_ollama_daemon(binary: str, wait_s: int = 20) -> bool:
    """Lance `ollama serve` en tache de fond, attend qu'il reponde."""
    try:
        subprocess.Popen([binary, "serve"],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception as e:
        print(f"  {c('red','✗')} impossible de lancer 'ollama serve' : {e}")
        return False
    for _ in range(wait_s):
        if _ollama_daemon_up():
            return True
        time.sleep(1)
    return False


def _pull_ollama_model(binary: str, model: str) -> bool:
    """Pull bloquant, affiche la progression Ollama."""
    print(f"  {c('cyan','⇩')} pull du modele {model} (une seule fois, ~2 GB)…")
    r = subprocess.run([binary, "pull", model])
    return r.returncode == 0


def ensure_ollama_ready(auto: bool = False, install_missing: bool = True) -> bool:
    """Setup complet Ollama pour traduction locale privee.

    - Detecte le binaire, l'installe si absent (avec confirmation utilisateur)
    - Lance le daemon si pas up
    - Pull le modele de traduction si absent
    - Retourne True si tout est pret, False si on doit fallback

    auto=True  : pas de prompt (utile pour CI, .app relance)
    install_missing=False : n'installe jamais, se limite au probe
    """
    model = _ollama_model()

    # 1. binaire present ?
    binary = _which("ollama")
    if not binary:
        if not install_missing:
            return False
        if not _prompt_yes("Ollama n'est pas installe. L'installer maintenant (~50 MB) ?", auto):
            return False
        if not _install_ollama():
            return False
        binary = _which("ollama")
        if not binary:
            # sur macOS avec brew, PATH peut ne pas etre rafraichi immediatement
            for candidate in ("/usr/local/bin/ollama", "/opt/homebrew/bin/ollama", "/usr/bin/ollama"):
                if os.path.exists(candidate):
                    binary = candidate
                    break
        if not binary:
            print(f"  {c('red','✗')} Ollama installe mais binaire introuvable dans le PATH.")
            return False

    # 2. daemon up ?
    if not _ollama_daemon_up():
        print(f"  {c('cyan','⇢')} demarrage du daemon Ollama…")
        if not _start_ollama_daemon(binary):
            print(f"  {c('red','✗')} daemon Ollama ne repond pas.")
            return False

    # 3. modele present ?
    if not _ollama_model_present(model):
        if not _prompt_yes(f"Modele {model} absent (~2 GB). Le telecharger maintenant ?", auto):
            return False
        if not _pull_ollama_model(binary, model):
            print(f"  {c('red','✗')} pull de {model} a echoue.")
            return False

    return True


LANG_NAMES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "zh": "Chinese",
    "ja": "Japanese",
}


def _try_ollama(text: str, target: str = "en", timeout: int = 20) -> Optional[str]:
    """Traduit vers `target` via Ollama local. `target` : code ISO 639-1
    (en/fr/es/de/zh/ja...). Utilise ensure_ollama_ready() en amont."""
    host   = _ollama_host()
    model  = _ollama_model()
    tname  = LANG_NAMES.get(target, target)
    prompt = (f"Translate the following text to concise, natural {tname}. "
              "Return ONLY the translation, no preamble, no quotes.\n\n" + text)
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.1, "num_predict": 400}}).encode()
    try:
        req = urllib.request.Request(host + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        out = (data.get("response") or "").strip()
        return out or None
    except Exception:
        return None


def _try_deep_translator(text: str, target: str = "en") -> Optional[str]:
    """Traduit vers `target` via deep_translator (GoogleTranslator, pas de cle)."""
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="auto", target=target).translate(text[:4900])
    except Exception:
        return None


def translate(text: str, target: str = "en", max_len: int = 900) -> str:
    """Traduit vers la langue cible avec cache + fallback silencieux.
    target : code ISO ("en" par defaut, "fr" pour francais, etc.).
    Retourne "" si aucun backend dispo ou texte vide."""
    global _TR_BACKEND
    text = (text or "").strip()
    if not text:
        return ""
    text = text[:max_len]
    key  = hashlib.md5((target + "\x00" + text).encode("utf-8"), usedforsecurity=False).hexdigest()
    _load_translation_cache()
    if key in _TR_CACHE:
        return _TR_CACHE[key]

    tried = [_TR_BACKEND] if _TR_BACKEND else ["ollama", "deep_translator"]
    for backend in tried + (["ollama", "deep_translator"] if not _TR_BACKEND else []):
        if backend == "ollama":
            out = _try_ollama(text, target=target)
        elif backend == "deep_translator":
            out = _try_deep_translator(text, target=target)
        else:
            continue
        if out:
            _TR_BACKEND = backend
            _TR_CACHE[key] = out
            return out
    return ""


def translate_to_en(text: str, max_len: int = 900) -> str:
    """Alias retrocompatible : traduit vers EN."""
    return translate(text, target="en", max_len=max_len)


# ══════════════════════════════════════════════════════════════════════════════
# OPML EXPORT
# ══════════════════════════════════════════════════════════════════════════════

def export_opml(path: Path) -> None:
    now = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
    groups: dict[str, list] = {}
    for f in ALL_FEEDS:
        groups.setdefault(f["theme"], []).append(f)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<opml version="2.0">',
        f'  <head><title>Daily Hacker News Feeds</title><dateCreated>{now}</dateCreated></head>',
        '  <body>',
    ]
    for theme in THEME_ORDER:
        if theme not in groups:
            continue
        cfg = THEMES[theme]
        lines.append(f'    <outline text="{cfg["icon"]} {cfg["title"]}">')
        for f in groups[theme]:
            if f.get("ftype") in ("json_kev", "gh_md"):
                continue
            lines.append(
                f'      <outline type="rss" text="{escape(f["label"])}" '
                f'xmlUrl="{escape(f["url"])}" htmlUrl="{escape(f["url"])}"/>'
            )
        lines.append('    </outline>')
    lines += ['  </body>', '</opml>']
    path.write_text("\n".join(lines), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# RENDER — HTML
# ══════════════════════════════════════════════════════════════════════════════

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#e6edf3;line-height:1.6;font-size:15px}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
/* HEADER */
.hdr{background:#161b22;border-bottom:1px solid #30363d;padding:1.6rem 1.5rem;text-align:center}
.hdr h1{font-size:1.9rem;font-weight:700;letter-spacing:-0.5px}
.hdr h1 em{color:#58a6ff;font-style:normal}
.hdr .sub{color:#8b949e;font-size:.88rem;margin-top:.35rem}
/* STATS BAR */
.stats{display:flex;flex-wrap:wrap;gap:.6rem;justify-content:center;margin-top:1.1rem}
.stat{background:#21262d;border:1px solid #30363d;border-radius:8px;padding:.4rem .9rem;font-size:.82rem;display:flex;gap:.5rem;align-items:center}
.stat strong{font-size:1.15rem;font-weight:700}
/* TOC */
.toc{max-width:860px;margin:1.2rem auto .4rem;padding:0 1.5rem}
.toc-inner{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1rem 1.2rem}
.toc-inner h2{font-size:.82rem;text-transform:uppercase;letter-spacing:.08em;color:#8b949e;margin-bottom:.7rem}
.toc-links{display:flex;flex-wrap:wrap;gap:.5rem}
.toc-a{background:#21262d;border:1px solid #30363d;border-radius:6px;padding:.28rem .75rem;font-size:.82rem;transition:background .12s}
.toc-a:hover{background:#30363d;text-decoration:none}
/* CONTAINER */
.wrap{max-width:860px;margin:0 auto;padding:.8rem 1.5rem 3rem}
/* SECTION */
.sec{margin-bottom:2.2rem;scroll-margin-top:1rem}
.sec-head{display:flex;align-items:center;gap:.55rem;padding:.7rem 1rem;border-radius:8px 8px 0 0;border-left:4px solid}
.sec-head h2{font-size:1rem;font-weight:600}
.sec-head .badge{margin-left:auto;background:rgba(255,255,255,.1);border-radius:10px;padding:.1rem .55rem;font-size:.76rem}
/* CARDS */
.cards{border:1px solid #30363d;border-top:none;border-radius:0 0 8px 8px;overflow:hidden}
.card{padding:.85rem 1.1rem;border-bottom:1px solid #21262d;transition:background .1s}
.card:last-child{border-bottom:none}
.card:hover{background:#161b22}
/* CARD CONTENT */
.ct{font-size:.92rem;font-weight:600;margin-bottom:.2rem}
.ct a{color:#58a6ff}
.ct a:hover{color:#79c0ff}
.cm{font-size:.76rem;color:#8b949e;display:flex;gap:.8rem;flex-wrap:wrap;margin-bottom:.3rem}
.cm .src{color:#f0883e;font-weight:500}
.cs{font-size:.82rem;color:#c9d1d9;margin-bottom:.3rem}
.cs-fr{font-size:.82rem;color:#79c0ff;font-style:italic;margin-bottom:.3rem}
.cs-en{font-size:.82rem;color:#a5d6a7;font-style:italic;margin-bottom:.3rem}
.ce{font-size:.78rem;background:#1c2128;color:#ffa657;border-radius:4px;padding:.25rem .55rem;font-family:monospace;margin-bottom:.3rem;overflow-x:auto}
.ctags{display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.25rem}
.ctag{background:#21262d;border-radius:4px;padding:.05rem .4rem;font-size:.72rem;color:#8b949e}
.ctag.kev{background:#3d1010;color:#ff7b72}
.ctag.exploit{background:#3d2010;color:#ffa657}
.ctag.hi{background:#1a3a1a;color:#56d364}
/* SEV PILLS */
.sev{display:inline-block;border-radius:4px;padding:.05rem .45rem;font-size:.72rem;font-weight:700;margin-right:.4rem}
.sev-critical{background:#5d1f1a;color:#ff7b72}
.sev-high{background:#3d2010;color:#ffa657}
.sev-medium{background:#3d3210;color:#e3b341}
.sev-low{background:#10253d;color:#79c0ff}
/* FOOTER */
.foot{text-align:center;padding:2rem;color:#484f58;font-size:.78rem;border-top:1px solid #21262d}
/* RESPONSIVE */
@media(max-width:560px){.stats{gap:.4rem}.stat{padding:.3rem .6rem}}
/* SEARCH */
.searchbar{max-width:1100px;margin:1rem auto;padding:0 1rem}
.searchbar input{width:100%;box-sizing:border-box;padding:.7rem 1rem;font-size:1rem;
  border-radius:10px;border:1px solid #30363d;background:#161b22;color:#e6edf3}
.searchbar input:focus{outline:none;border-color:#58a6ff}
/* PAGER */
.pager{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem;margin:.8rem 0 .4rem}
.pinfo{color:#8b949e;font-size:.85rem;margin-right:.5rem}
.pbtns{display:inline-flex;gap:.3rem;flex-wrap:wrap}
.pbtn{min-width:2rem;padding:.3rem .55rem;border-radius:7px;border:1px solid #30363d;
  background:#21262d;color:#e6edf3;cursor:pointer;font-size:.85rem}
.pbtn.on{background:#58a6ff;border-color:#58a6ff;color:#0d1117}
.pbtn:disabled{opacity:.35;cursor:default}
.pdots{color:#484f58;padding:0 .2rem}
"""

def _sev_pill(sev: str) -> str:
    s = sev.lower()
    cls = f"sev-{s}" if s in ("critical","high","medium","low") else "sev-low"
    return f'<span class="sev {cls}">{escape(sev.upper())}</span>' if sev else ""

def _build_card(art: Article) -> str:
    pills = _sev_pill(art.severity)
    if art.kev:
        pills += '<span class="ctag kev">KEV</span> '
    if art.exploit:
        pills += '<span class="ctag exploit">EXPLOIT</span> '

    meta_parts = [
        f'<span class="src">⊕ {escape(art.source)}</span>',
        f'<span>{art.date_fmt} · {art.age_str}</span>',
    ]
    if art.cves:
        meta_parts.append('<span>' + " ".join(escape(c) for c in art.cves[:3]) + '</span>')
    if art.score:
        meta_parts.append(f'<span>Pentest {art.score}/10</span>')

    # English-first: show the English translation when available, otherwise the
    # native summary (English sources are already English). No dual-language clutter.
    if art.summary_en:
        disp_sum = art.summary_en
    elif art.lang == "en":
        disp_sum = art.summary
    else:
        disp_sum = art.summary or (art.summary_fr if isinstance(art.summary_fr, str) else "")
    body = ""
    if disp_sum:
        body += f'<div class="cs">{escape(disp_sum)}</div>'
    if art.cmd:
        body += f'<div class="ce">$ {escape(art.cmd)}</div>'

    all_tags = list(art.tags[:5])
    tags_html = ""
    if all_tags:
        tags_html = '<div class="ctags">' + "".join(
            f'<span class="ctag">{escape(t)}</span>' for t in all_tags
        ) + '</div>'

    title_disp = art.title_en or art.title
    search_txt = " ".join(filter(None, [
        art.title, art.title_en, art.source, art.summary, art.summary_en,
        art.summary_fr if isinstance(art.summary_fr, str) else " ".join(art.summary_fr or []),
        " ".join(art.cves or []), " ".join(art.tags or []),
    ])).lower()

    return (
        f'<div class="card" data-s="{escape(search_txt, quote=True)}">'
        f'<div class="ct">{pills}<a href="{escape(art.url) if str(art.url).startswith(("http://","https://","mailto:")) else "#"}" target="_blank" rel="noopener">{escape(title_disp)}</a></div>'
        f'<div class="cm">{"".join(meta_parts)}</div>'
        f'{body}{tags_html}'
        f'</div>'
    )

def render_html(by_theme: dict, args, total: int, n_feeds: int, n_ok: int) -> str:
    now    = datetime.now()
    ds     = now.strftime("%d/%m/%Y %H:%M")
    period = f"{args.days}d" if args.days > 1 else "24h"

    # stats
    stats = ""
    for t in THEME_ORDER:
        arts = by_theme.get(t, [])
        if not arts:
            continue
        cfg = THEMES[t]
        stats += (
            f'<div class="stat">'
            f'<strong style="color:{cfg["color"]}">{len(arts)}</strong>'
            f'{cfg["icon"]} {cfg["title"]}'
            f'</div>'
        )

    # toc
    toc = ""
    for t in THEME_ORDER:
        arts = by_theme.get(t, [])
        if not arts:
            continue
        cfg = THEMES[t]
        toc += f'<a class="toc-a" href="#{t}">{cfg["icon"]} {cfg["title"]} <b>({len(arts)})</b></a>'

    # sections
    sections = ""
    for t in THEME_ORDER:
        arts = by_theme.get(t, [])
        if not arts:
            continue
        cfg  = THEMES[t]
        cards = "".join(_build_card(a) for a in arts)
        sections += (
            f'<div class="sec" id="{t}" data-page="1">'
            f'<div class="sec-head" style="background:{cfg["bg"]};border-left-color:{cfg["color"]}">'
            f'<span style="font-size:1.25rem">{cfg["icon"]}</span>'
            f'<h2>{cfg["title"]}</h2>'
            f'<span class="badge">{len(arts)} articles</span>'
            f'</div>'
            f'<div class="cards">{cards}</div>'
            f'<div class="pager"></div>'
            f'</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Hacker News — {now.strftime('%d/%m/%Y')}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="hdr">
  <h1>🛡 <em>Daily</em> Hacker News</h1>
  <div class="sub">Security &amp; Pentest Watch — {ds} · {total} articles · {n_ok}/{n_feeds} sources · window {period}</div>
  <div class="stats">{stats}</div>
</div>
<div class="searchbar"><input id="q" type="search" placeholder="🔎 Rechercher (titre, source, CVE, tag…)" autocomplete="off"></div>
<div class="toc"><div class="toc-inner">
  <h2>Quick navigation</h2>
  <div class="toc-links">{toc}</div>
</div></div>
<div class="wrap">{sections}</div>
<div class="foot">Daily Hacker News · generated {ds} · <a href="secjournal_feeds.opml">OPML</a></div>
<script>
const PER={args.per_page};
const q=document.getElementById('q');
function btn(label,target,dis,on){{return '<button class="pbtn'+(on?' on':'')+'"'+(dis?' disabled':'')+' data-t="'+target+'">'+label+'</button>';}}
function pager(sec,pages,page,count){{
  const nav=sec.querySelector('.pager');
  if(pages<=1){{nav.innerHTML=count?('<span class="pinfo">'+count+' result'+(count>1?'s':'')+'</span>'):'';return;}}
  let h='<span class="pinfo">'+count+' results · page '+page+'/'+pages+'</span><span class="pbtns">';
  h+=btn('‹',page>1?page-1:1,page===1,false);
  for(let p=1;p<=pages;p++){{if(p===1||p===pages||Math.abs(p-page)<=2)h+=btn(p,p,false,p===page);else if(Math.abs(p-page)===3)h+='<span class="pdots">…</span>';}}
  h+=btn('›',page<pages?page+1:pages,page===pages,false)+'</span>';nav.innerHTML=h;
}}
function apply(){{
  const terms=(q.value||'').toLowerCase().trim().split(/\\s+/).filter(Boolean);
  document.querySelectorAll('.sec').forEach(sec=>{{
    const cards=[...sec.querySelectorAll('.card')];
    const match=cards.filter(c=>terms.every(t=>(c.dataset.s||'').includes(t)));
    cards.forEach(c=>c.style.display='none');
    let page=parseInt(sec.dataset.page||'1');
    const pages=Math.max(1,Math.ceil(match.length/PER));
    if(page>pages)page=pages;sec.dataset.page=page;
    match.slice((page-1)*PER,page*PER).forEach(c=>c.style.display='');
    pager(sec,pages,page,match.length);
    sec.style.display=(terms.length&&match.length===0)?'none':'';
  }});
}}
document.addEventListener('click',e=>{{const b=e.target.closest('.pbtn');if(!b)return;const sec=b.closest('.sec');sec.dataset.page=b.dataset.t;apply();sec.scrollIntoView({{behavior:'smooth',block:'start'}});}});
q.addEventListener('input',()=>{{document.querySelectorAll('.sec').forEach(s=>s.dataset.page='1');apply();}});
apply();
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# RENDER — MARKDOWN
# ══════════════════════════════════════════════════════════════════════════════

def render_json(by_theme: dict, args, total: int) -> str:
    now = datetime.now()
    stats = {theme: len(arts) for theme, arts in by_theme.items()}
    items = []
    for theme, arts in by_theme.items():
        for a in arts:
            items.append({
                "cat":      theme,
                "title":    a.title_en or a.title,
                "title_orig": a.title,
                "lang":     a.lang,
                "url":      a.url,
                "source":   a.source,
                "date":     a.date_fmt,
                "severity": a.severity,
                "summary":  (a.summary_en or a.summary or "")[:200],
                "summary_en": (a.summary_en or "")[:200],
                "summary_fr": (a.summary_fr or "")[:200],
                "heat":     round(float(a.heat or 0.0), 3),
                "kev":      a.kev,
                "exploit":  a.exploit,
                "cves":     a.cves[:3],
            })
    return json.dumps({
        "generated": now.strftime("%d/%m/%Y %H:%M"),
        "total":     total,
        "stats":     stats,
        "items":     items,
    }, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# STORE DURABLE + RECHERCHE (interface réutilisable par d'autres agents/scripts)
# ══════════════════════════════════════════════════════════════════════════════

def _art_to_record(a: Article, theme: str) -> dict:
    return {
        "uid": a.uid, "cat": theme, "title": a.title_en or a.title,
        "title_orig": a.title, "lang": a.lang, "url": a.url,
        "source": a.source, "date": a.date_fmt, "published": a.published.isoformat(),
        "severity": a.severity, "summary": (a.summary or "")[:400],
        "summary_fr": (a.summary_fr or "")[:400],
        "summary_en": (a.summary_en or "")[:400],
        "title_en": (a.title_en or "")[:300],
        "heat": float(a.heat or 0.0),
        "kev": a.kev, "exploit": a.exploit,
        "cves": a.cves[:5], "tags": a.tags[:8],
    }


def persist_store(by_theme: dict) -> int:
    """Ajoute les items du run au store JSONL (dédup par URL, cap STORE_CAP).
    C'est le backlog interrogé par search_journal() / --search."""
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, dict] = {}
        if STORE.is_file():
            for line in STORE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get("url"):
                        existing[r["url"]] = r
                except Exception:
                    pass
        for theme, arts in by_theme.items():
            for a in arts:
                existing[a.url] = _art_to_record(a, theme)
        records = sorted(existing.values(), key=lambda r: r.get("published", ""), reverse=True)[:STORE_CAP]
        with STORE.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return len(records)
    except Exception as e:
        print(f"[!] store not written ({e})", file=sys.stderr)
        return 0


def _load_store_records() -> list[dict]:
    recs: list[dict] = []
    if STORE.is_file():
        for line in STORE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    if not recs:  # fallback: last generated feed.json
        fj = SITE_DIR / "feed.json"
        if fj.is_file():
            try:
                recs = (json.loads(fj.read_text(encoding="utf-8")) or {}).get("items", [])
            except Exception:
                recs = []
    return recs


def search_journal(query: str, limit: int = 50, theme: str = "", records: list[dict] | None = None) -> list[dict]:
    """Recherche plein-texte (AND sur les termes) dans le store Daily Hacker News.

    Interface stable destinée à d'autres agents/scripts : importable directement
    (`from secjournal import search_journal`) ou via `--search` en CLI/JSON.
    Trie par date de publication décroissante.
    """
    recs  = records if records is not None else _load_store_records()
    terms = [t for t in re.split(r"\s+", query.strip().lower()) if t]
    out   = []
    for r in recs:
        if theme and r.get("cat") != theme:
            continue
        hay = " ".join(str(r.get(k, "")) for k in ("title", "source", "summary", "summary_fr", "summary_en", "cat")).lower()
        hay += " " + " ".join(map(str, r.get("cves", []) or [])).lower()
        hay += " " + " ".join(map(str, r.get("tags", []) or [])).lower()
        if all(t in hay for t in terms):
            out.append(r)
    out.sort(key=lambda r: r.get("published", ""), reverse=True)
    return out[:limit] if limit else out


def render_md(by_theme: dict, args, total: int) -> str:
    now = datetime.now()
    ds  = now.strftime("%d/%m/%Y %H:%M")
    period = f"{args.days}d" if args.days > 1 else "24h"
    lines = [
        f"# 🛡 Daily Hacker News — {now.strftime('%d/%m/%Y')}",
        "",
        f"> Security & Pentest Watch · {ds} · **{total} articles** · window {period}",
        "",
        "## Sommaire",
        "",
    ]
    for t in THEME_ORDER:
        arts = by_theme.get(t, [])
        if arts:
            cfg = THEMES[t]
            lines.append(f"- {cfg['icon']} [{cfg['title']} ({len(arts)})](#{t.lower()})")
    lines += ["", "---", ""]

    for t in THEME_ORDER:
        arts = by_theme.get(t, [])
        if not arts:
            continue
        cfg = THEMES[t]
        lines += [f"## {cfg['icon']} {cfg['title']}", ""]
        for art in arts:
            pills = []
            if art.severity:
                pills.append(f"`{art.severity.upper()}`")
            if art.kev:
                pills.append("`KEV`")
            if art.exploit:
                pills.append("`EXPLOIT`")
            pill_str = " ".join(pills) + " " if pills else ""
            lines.append(f"### {pill_str}[{art.title_en or art.title}]({art.url})")
            meta = [f"**{art.source}**", art.date_fmt, f"*{art.age_str}*"]
            if art.score:
                meta.append(f"pentest {art.score}/10")
            if art.cves:
                meta.append(" ".join(art.cves[:3]))
            lines.append(" · ".join(meta))
            # English-first summary
            if art.summary_en:
                disp = art.summary_en
            elif art.lang == "en":
                disp = art.summary
            else:
                disp = art.summary or (art.summary_fr if isinstance(art.summary_fr, str) else "")
            if disp:
                lines.append(f"> {disp}")
            if art.cmd:
                lines.append(f"```\n$ {art.cmd}\n```")
            if art.tags:
                lines.append("`" + "` `".join(art.tags[:5]) + "`")
            lines.append("")
        lines += ["---", ""]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# TERMINAL DISPLAY (résumé)
# ══════════════════════════════════════════════════════════════════════════════

ANSI = {
    "red":"\033[91m","yellow":"\033[93m","green":"\033[92m","cyan":"\033[96m",
    "bold":"\033[1m","reset":"\033[0m","magenta":"\033[95m","blue":"\033[94m",
    "orange":"\033[38;5;208m","grey":"\033[90m",
}
def c(col, txt): return f"{ANSI.get(col,'')}{txt}{ANSI['reset']}"


def print_summary(by_theme: dict) -> None:
    print(c("bold", "\n═══ Daily Hacker News — Summary ═══\n"))
    for t in THEME_ORDER:
        arts = by_theme.get(t, [])
        if not arts:
            continue
        cfg = THEMES[t]
        print(c("bold", f"  {cfg['icon']}  {cfg['title']}  ({len(arts)} articles)"))
        for art in arts[:5]:
            sev  = f"[{art.severity[:4].upper()}]" if art.severity else "     "
            kev  = c("red"," KEV") if art.kev else ""
            expl = c("yellow"," EXP") if art.exploit else ""
            score= f" {c('cyan',str(art.score)+'/10')}" if art.score else ""
            title = (art.title_en or art.title)[:62]
            print(f"    {c('grey', art.date_fmt)}  {c('orange',sev)}{kev}{expl}{score}  {title}")
            gist = art.summary_en or (art.summary if art.lang == "en" else art.summary_fr)
            if gist:
                print(f"    {c('cyan','  → '+gist[:80])}")
        if len(arts) > 5:
            print(f"    {c('grey', f'… +{len(arts)-5} more')}")
        print()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Daily Hacker News — security / pentest intel journal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python3 scripts/secjournal.py                      # 24h, HTML
          python3 scripts/secjournal.py --days 7             # last week
          python3 scripts/secjournal.py --output both        # HTML + Markdown
          python3 scripts/secjournal.py --themes CVE,Exploit # selected themes
          python3 scripts/secjournal.py --max 30             # max 30/theme
          python3 scripts/secjournal.py --open               # open the HTML
          python3 scripts/secjournal.py --export-opml        # export OPML
          python3 scripts/secjournal.py --no-fetch           # rss_watcher only
          python3 scripts/secjournal.py --search "log4j"     # search (JSON)
        """),
    )
    ap.add_argument("--days",        type=int, default=1,
                    help="time window in days (default: 1)")
    ap.add_argument("--output",      choices=["html","md","both"], default="html",
                    help="output format")
    ap.add_argument("--themes",      default="",
                    help="CSV of themes: CVE,Exploit,News-EN,News-FR,Outils,CTF")
    ap.add_argument("--max",         type=int, default=500,
                    help="articles kept per theme (default: 500 = 10 pages x 50)")
    ap.add_argument("--per-page",    dest="per_page", type=int, default=50,
                    help="articles per page in the HTML (default: 50)")
    ap.add_argument("--open",        dest="open", action="store_true", default=None,
                    help="open the HTML in the browser (default when run as .app)")
    ap.add_argument("--no-open",     dest="open", action="store_false",
                    help="do not open the HTML automatically")
    ap.add_argument("--export-opml", action="store_true",
                    help="export all RSS feeds as .opml")
    ap.add_argument("--no-fetch",    action="store_true",
                    help="use rss_watcher items only (no refetch)")
    ap.add_argument("--workers",     type=int, default=12,
                    help="parallel threads (default: 12)")
    ap.add_argument("--search",      default="",
                    help="search mode: query the store and emit JSON (for agents/scripts)")
    ap.add_argument("--limit",       type=int, default=50,
                    help="max results for --search (default: 50)")
    ap.add_argument("--sources",     default="local",
                    help="csv sources: local,github,gitee,gitlab,huggingface,codeberg "
                         "(default: local). Example: --sources local,github,gitee")
    ap.add_argument("--lang",        default="en", choices=["en","fr","es","de","zh","ja"],
                    help="target language for translating --search results (default: en)")
    ap.add_argument("--no-translate-results", dest="translate_results",
                    action="store_false", default=True,
                    help="do not translate --search results")
    ap.add_argument("--translate",   dest="translate", action="store_true", default=True,
                    help="auto-translate non-English titles+summaries to EN via Ollama/deep_translator (default: on)")
    ap.add_argument("--no-translate",dest="translate", action="store_false",
                    help="disable EN translation (faster, less traffic)")
    ap.add_argument("--translate-max", type=int, default=200,
                    help="max articles translated per run (default: 200; results are cached)")
    ap.add_argument("--setup-translate", action="store_true",
                    help="install Ollama + pull the translation model, then exit (interactive setup)")
    ap.add_argument("--auto-install",  action="store_true",
                    help="install Ollama without asking (useful in CI or for a .app)")
    ap.add_argument("--no-install",    action="store_true",
                    help="never offer to install Ollama — fall back directly")
    ap.add_argument("--no-trending", dest="trending", action="store_false", default=True,
                    help="disable the Trending Now section")
    ap.add_argument("--verify-feeds", action="store_true",
                    help="probe every feed URL and emit a JSON report (dead/quiet/ok)")
    args = ap.parse_args()

    if args.setup_translate:
        print(c("bold", "\n🌐 Translation setup — local Ollama\n"))
        ok = ensure_ollama_ready(auto=args.auto_install, install_missing=not args.no_install)
        if ok:
            # quick self-test (French input to exercise FR→EN)
            out = translate_to_en("Bonjour, ceci est un test de traduction.")
            if out:
                print(f"  {c('green','✓')} test OK ({_TR_BACKEND}): {out}")
            else:
                print(f"  {c('red','✗')} setup looks OK but the translation test failed")
        else:
            print(f"  {c('grey','○')} Ollama not set up — the tool will use deep_translator or skip")
        return

    if args.search:
        theme    = args.themes.split(",")[0].strip() if args.themes.strip() else ""
        srcs     = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
        merged: list[dict] = []

        # 1. local store (existing behaviour)
        if "local" in srcs:
            for r in search_journal(args.search, limit=args.limit, theme=theme):
                r.setdefault("source", "local")
                merged.append(r)

        # 2. external open platforms (opt-in via --sources)
        external_srcs = [s for s in srcs if s != "local"]
        if external_srcs:
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                from search_external import search_all as _search_ext
                for r in _search_ext(args.search, external_srcs, limit=args.limit):
                    merged.append(r)
            except Exception as e:
                print(f"[!] search_external failed: {e}", file=sys.stderr)

        # 3. translate results into --lang (best-effort; no-op if backend absent
        #    or --no-translate-results). Skips items already in the target lang.
        if args.translate_results and merged:
            _load_translation_cache()
            for r in merged:
                src_lang = (r.get("lang") or "").lower()
                if src_lang == args.lang:
                    continue
                for field in ("title", "description", "summary", "summary_fr"):
                    v = r.get(field)
                    if not v or not isinstance(v, str):
                        continue
                    translated = translate(v, target=args.lang)
                    if translated:
                        r[f"{field}_{args.lang}"] = translated
            try:
                _save_translation_cache()
            except Exception:
                pass

        print(json.dumps({
            "query":    args.search,
            "sources":  srcs,
            "lang":     args.lang,
            "count":    len(merged),
            "results":  merged,
        }, ensure_ascii=False, indent=2))
        return

    if args.export_opml:
        p = SITE_DIR / "secjournal_feeds.opml"
        export_opml(p)
        print(f"{c('green','✓')} OPML → {p}")
        return

    if args.verify_feeds:
        report = verify_feeds(ALL_FEEDS, workers=args.workers)
        # sort: ok first, then quiet, then dead
        order = {"ok": 0, "quiet": 1, "dead": 2}
        report.sort(key=lambda r: (order.get(r["status"], 3), r["label"]))
        n_ok    = sum(1 for r in report if r["status"] == "ok")
        n_quiet = sum(1 for r in report if r["status"] == "quiet")
        n_dead  = sum(1 for r in report if r["status"] == "dead")
        summary = {
            "total":  len(report),
            "ok":     n_ok,
            "quiet":  n_quiet,
            "dead":   n_dead,
            "feeds":  report,
        }
        # human-readable to stderr, JSON to stdout so it stays pipeable
        for r in report:
            mark = {"ok": c('green','✓'), "quiet": c('grey','○'),
                    "dead": c('red','✗')}.get(r["status"], "?")
            note = f" · {r['diag']}" if r["diag"] else ""
            print(f"  {mark} [{r['theme']:<9}] {r['label']:<32} "
                  f"{r['articles']:>3} arts{note}",
                  file=sys.stderr)
        print(f"\n  total={len(report)} ok={n_ok} quiet={n_quiet} dead={n_dead}",
              file=sys.stderr)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    theme_filter = {t.strip() for t in args.themes.split(",")} if args.themes.strip() else None
    cutoff       = datetime.now(timezone.utc) - timedelta(days=args.days)
    period       = f"{args.days}d" if args.days > 1 else "24h"

    # ── Sélection des feeds ───────────────────────────────────────────────────
    feeds = ALL_FEEDS
    if theme_filter:
        feeds = [f for f in feeds if f["theme"] in theme_filter]

    print(c("bold", f"\n🛡  Daily Hacker News · {period} · {len(feeds)} sources\n"))

    # ── Fetch parallèle ───────────────────────────────────────────────────────
    all_arts: list[Article] = []
    n_ok = 0

    n_dead = 0
    if not args.no_fetch:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(fetch_feed_verbose, f, cutoff): f for f in feeds}
            for fut in as_completed(futures):
                feed = futures[fut]
                try:
                    arts, diag = fut.result()
                    if arts:
                        n_ok += 1
                        mark = c("green","✓")
                        note = ""
                    elif diag and ("HTTP" in diag or "URL:" in diag or "URLError" in diag):
                        n_dead += 1
                        mark = c("red","✗")
                        note = f" ← {diag}"
                    else:
                        mark = c("grey","○")
                        note = f" ← {diag}" if diag else ""
                    all_arts.extend(arts)
                    print(f"  {mark} {feed['label']:<32} {len(arts):>3} articles{note}")
                except Exception as e:
                    n_dead += 1
                    print(f"  {c('red','✗')} {feed['label']:<32} {e}")
        if n_dead:
            print(f"\n{c('bold','⚠')} {n_dead} dead feed(s) — run --verify-feeds for a full audit")

    # ── Intégrer rss_watcher items (Ollama-enriched) ──────────────────────────
    rw_arts = load_rss_watcher_items(cutoff)
    if rw_arts:
        print(f"\n  {c('cyan','+')} rss_watcher: {len(rw_arts)} Ollama items loaded")
        all_arts.extend(rw_arts)

    # ── Déduplication ─────────────────────────────────────────────────────────
    seen: set[str] = set()
    unique: list[Article] = []
    for art in all_arts:
        if art.uid not in seen and art.url:
            seen.add(art.uid)
            unique.append(art)

    # ── Grouper par thème ─────────────────────────────────────────────────────
    by_theme: dict[str, list[Article]] = {t: [] for t in THEME_ORDER}
    for art in sorted(unique, key=lambda a: a.published, reverse=True):
        bucket = by_theme.get(art.theme)
        if bucket is not None and len(bucket) < args.max:
            if theme_filter is None or art.theme in theme_filter:
                bucket.append(art)

    # ── Heat score sur tous les articles retenus ─────────────────────────────
    for arts in by_theme.values():
        for a in arts:
            a.heat = compute_heat(a)

    # ── Trending Now (multi-source CVE + KEV frais + top-heat 24h) ───────────
    if args.trending and "Trending" in by_theme:
        by_theme["Trending"] = build_trending(by_theme, min_sources=2, top_k=30)
        n_trend = len(by_theme["Trending"])
        if n_trend:
            print(f"{c('bold','🔥')} Trending: {n_trend} articles multi-source / KEV / top-heat")

    # ── Traduction EN (auto-setup Ollama > fallback deep_translator) ─────────
    if args.translate:
        _load_translation_cache()
        # Auto-setup Ollama en premier (prompt Y/n sauf --auto-install / --no-install)
        # Fallback silencieux vers deep_translator si Ollama pas disponible.
        if not args.no_install and not _ollama_daemon_up():
            ready = ensure_ollama_ready(auto=args.auto_install,
                                        install_missing=not args.no_install)
            if not ready:
                # message discret, on continue avec deep_translator si dispo
                print(f"  {c('grey','ℹ')} translation: falling back to deep_translator (Ollama unavailable)")

        # Everything must read in English. Any article whose source language is
        # not English gets BOTH its title and its summary translated. Foreign
        # themes first (News-FR / News-CN), then anything else flagged non-EN.
        priority = ["Trending", "Threat", "CVE", "News-FR", "News-CN",
                    "Exploit", "News-EN", "Outils", "CTF"]
        candidates: list[Article] = []
        for t in priority:
            for a in by_theme.get(t, []):
                if a.lang == "en":
                    continue  # already English — nothing to translate
                needs_title = not a.title_en and a.title
                needs_sum   = not a.summary_en and (a.summary or a.summary_fr)
                if needs_title or needs_sum:
                    candidates.append(a)
        candidates = candidates[:args.translate_max]
        if candidates:
            print(f"{c('cyan','🌐')} EN translation: {len(candidates)} articles to process…")

            def _translate_one(a: Article) -> bool:
                did = False
                if not a.title_en and a.title:
                    t_out = translate_to_en(a.title, max_len=300)
                    if t_out:
                        a.title_en = t_out
                        did = True
                if not a.summary_en:
                    src = a.summary or a.summary_fr
                    if src:
                        s_out = translate_to_en(src)
                        if s_out:
                            a.summary_en = s_out
                            did = True
                return did

            # Parallel: Ollama/deep_translator are network-bound, so a thread pool
            # turns a multi-minute sequential run into ~tens of seconds. Results are
            # cached to disk, so subsequent runs are near-instant.
            n_ok_tr = 0
            with ThreadPoolExecutor(max_workers=min(8, max(2, args.workers))) as ex:
                for did in ex.map(_translate_one, candidates):
                    if did:
                        n_ok_tr += 1
            _save_translation_cache()
            if n_ok_tr:
                print(f"  {c('green','✓')} {n_ok_tr} articles translated via {_TR_BACKEND}")
            elif _TR_BACKEND is None:
                print(f"  {c('grey','○')} no translation backend available (Ollama/deep_translator)")

    total = sum(len(v) for v in by_theme.values())
    print(f"\n{c('bold','📊')} {total} unique articles · {n_ok}/{len(feeds)} sources OK\n")

    n_store = persist_store(by_theme)
    print(f"{c('cyan','⛁')} store: {n_store} items indexed ({STORE})")

    print_summary(by_theme)

    # ── Génération des fichiers ───────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    html_path = None

    # Servable artifacts (HTML/OPML/JSON) go to SITE_DIR — the only dir the
    # server exposes. Internal Markdown stays in OUT_DIR, unreachable by the web.
    if args.output in ("html", "both"):
        html = render_html(by_theme, args, total, len(feeds), n_ok)
        html_path = SITE_DIR / f"secjournal_{ts}.html"
        html_path.write_text(html, encoding="utf-8")
        # OPML next to the HTML (the footer links to it relatively)
        opml_p = SITE_DIR / "secjournal_feeds.opml"
        if not opml_p.exists():
            export_opml(opml_p)
        print(f"{c('green','✓')} HTML  → {html_path}")

    if args.output in ("md", "both"):
        md   = render_md(by_theme, args, total)
        md_p = OUT_DIR / f"secjournal_{ts}.md"   # internal, not served
        md_p.write_text(md, encoding="utf-8")
        print(f"{c('green','✓')} MD    → {md_p}")

    # Always generate feed.json for the Garmin watch app (served)
    json_str  = render_json(by_theme, args, total)
    json_path = SITE_DIR / "feed.json"
    json_path.write_text(json_str, encoding="utf-8")
    print(f"{c('green','✓')} JSON  → {json_path}")

    # Auto-open : par défaut oui quand lancé en .app (frozen), sinon opt-in --open
    auto_open = args.open
    if auto_open is None:
        auto_open = getattr(sys, "frozen", False)

    if auto_open and html_path:
        try:
            subprocess.Popen(["open", str(html_path)])
        except Exception:
            pass

    print()


if __name__ == "__main__":
    main()
