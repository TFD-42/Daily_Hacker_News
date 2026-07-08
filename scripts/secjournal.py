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
KB_RSS     = DATA_ROOT / "knowledge" / "rss" / "items.jsonl"
STORE      = OUT_BASE / "knowledge" / "rss" / "journal_store.jsonl"
STORE_CAP  = 5000
OUT_DIR.mkdir(parents=True, exist_ok=True)

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
            print(f"[!] {fp.name} vide/invalide — liste intégrée utilisée", file=sys.stderr)
        except Exception as e:
            print(f"[!] {fp.name} ignoré ({e}) — liste intégrée utilisée", file=sys.stderr)
    return _BUILTIN_FEEDS


ALL_FEEDS: list[dict] = load_feeds()

THEMES: dict[str, dict] = {
    "CVE":     {"icon": "🔴", "title": "CVE & Vulnérabilités",      "color": "#e74c3c", "bg": "#2c0f0f"},
    "Exploit": {"icon": "💥", "title": "Exploits & PoC",            "color": "#e67e22", "bg": "#2c1a08"},
    "News-EN": {"icon": "🌐", "title": "Security News (EN)",        "color": "#3498db", "bg": "#0a1a2c"},
    "News-FR": {"icon": "🇫🇷", "title": "Actualités Sécurité (FR)", "color": "#2ecc71", "bg": "#0a2c10"},
    "Outils":  {"icon": "🛠",  "title": "Outils & Techniques",      "color": "#9b59b6", "bg": "#1a0a2c"},
    "CTF":     {"icon": "🏁", "title": "CTF & Labs",                "color": "#1abc9c", "bg": "#082c28"},
}

THEME_ORDER = ["CVE", "Exploit", "News-EN", "News-FR", "Outils", "CTF"]

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

    @property
    def uid(self) -> str:
        return hashlib.md5(self.url.encode()).hexdigest()[:10]

    @property
    def age_str(self) -> str:
        now = datetime.now(timezone.utc)
        delta = now - self.published
        h = int(delta.total_seconds() / 3600)
        if h < 1:
            return "à l'instant"
        if h < 24:
            return f"{h}h"
        return f"{delta.days}j"

    @property
    def date_fmt(self) -> str:
        return self.published.strftime("%d/%m %H:%M")

# ══════════════════════════════════════════════════════════════════════════════
# HTTP + PARSERS
# ══════════════════════════════════════════════════════════════════════════════

def http_get(url: str, timeout: int = 18) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA,
              "Accept": "application/rss+xml,application/xml,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


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
    raw = http_get(feed["url"])
    if not raw:
        return []
    ftype = feed.get("ftype", "rss")
    if ftype == "json_kev":
        return parse_kev_json(raw, feed["label"], cutoff)
    if ftype == "gh_md":
        return parse_gh_md(raw, feed["label"], feed["theme"])
    return parse_rss(raw, feed["label"], feed["theme"], cutoff)


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

    body = ""
    if art.summary_fr:
        sfr = art.summary_fr if isinstance(art.summary_fr, str) else " ".join(art.summary_fr)
        body += f'<div class="cs-fr">🇫🇷 {escape(sfr)}</div>'
    if art.summary:
        body += f'<div class="cs">{escape(art.summary)}</div>'
    if art.cmd:
        body += f'<div class="ce">$ {escape(art.cmd)}</div>'

    all_tags = list(art.tags[:5])
    tags_html = ""
    if all_tags:
        tags_html = '<div class="ctags">' + "".join(
            f'<span class="ctag">{escape(t)}</span>' for t in all_tags
        ) + '</div>'

    search_txt = " ".join(filter(None, [
        art.title, art.source, art.summary,
        art.summary_fr if isinstance(art.summary_fr, str) else " ".join(art.summary_fr or []),
        " ".join(art.cves or []), " ".join(art.tags or []),
    ])).lower()

    return (
        f'<div class="card" data-s="{escape(search_txt, quote=True)}">'
        f'<div class="ct">{pills}<a href="{escape(art.url) if str(art.url).startswith(("http://","https://","mailto:")) else "#"}" target="_blank" rel="noopener">{escape(art.title)}</a></div>'
        f'<div class="cm">{"".join(meta_parts)}</div>'
        f'{body}{tags_html}'
        f'</div>'
    )

def render_html(by_theme: dict, args, total: int, n_feeds: int, n_ok: int) -> str:
    now    = datetime.now()
    ds     = now.strftime("%d/%m/%Y %H:%M")
    period = f"{args.days}j" if args.days > 1 else "24h"

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
  <div class="sub">Veille Sécurité &amp; Pentest — {ds} · {total} articles · {n_ok}/{n_feeds} sources · période {period}</div>
  <div class="stats">{stats}</div>
</div>
<div class="searchbar"><input id="q" type="search" placeholder="🔎 Rechercher (titre, source, CVE, tag…)" autocomplete="off"></div>
<div class="toc"><div class="toc-inner">
  <h2>Navigation rapide</h2>
  <div class="toc-links">{toc}</div>
</div></div>
<div class="wrap">{sections}</div>
<div class="foot">Daily Hacker News · généré le {ds} · <a href="secjournal_feeds.opml">OPML</a></div>
<script>
const PER={args.per_page};
const q=document.getElementById('q');
function btn(label,target,dis,on){{return '<button class="pbtn'+(on?' on':'')+'"'+(dis?' disabled':'')+' data-t="'+target+'">'+label+'</button>';}}
function pager(sec,pages,page,count){{
  const nav=sec.querySelector('.pager');
  if(pages<=1){{nav.innerHTML=count?('<span class="pinfo">'+count+' résultat'+(count>1?'s':'')+'</span>'):'';return;}}
  let h='<span class="pinfo">'+count+' résultats · page '+page+'/'+pages+'</span><span class="pbtns">';
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
                "title":    a.title,
                "url":      a.url,
                "source":   a.source,
                "date":     a.date_fmt,
                "severity": a.severity,
                "summary":  a.summary[:200] if a.summary else "",
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
        "uid": a.uid, "cat": theme, "title": a.title, "url": a.url,
        "source": a.source, "date": a.date_fmt, "published": a.published.isoformat(),
        "severity": a.severity, "summary": (a.summary or "")[:400],
        "summary_fr": (a.summary_fr or "")[:400], "kev": a.kev, "exploit": a.exploit,
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
        print(f"[!] store non écrit ({e})", file=sys.stderr)
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
    if not recs:  # repli : dernier feed.json généré
        fj = OUT_DIR / "feed.json"
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
        hay = " ".join(str(r.get(k, "")) for k in ("title", "source", "summary", "summary_fr", "cat")).lower()
        hay += " " + " ".join(map(str, r.get("cves", []) or [])).lower()
        hay += " " + " ".join(map(str, r.get("tags", []) or [])).lower()
        if all(t in hay for t in terms):
            out.append(r)
    out.sort(key=lambda r: r.get("published", ""), reverse=True)
    return out[:limit] if limit else out


def render_md(by_theme: dict, args, total: int) -> str:
    now = datetime.now()
    ds  = now.strftime("%d/%m/%Y %H:%M")
    period = f"{args.days}j" if args.days > 1 else "24h"
    lines = [
        f"# 🛡 Daily Hacker News — {now.strftime('%d/%m/%Y')}",
        "",
        f"> Veille Sécurité & Pentest · {ds} · **{total} articles** · période {period}",
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
            lines.append(f"### {pill_str}[{art.title}]({art.url})")
            meta = [f"**{art.source}**", art.date_fmt, f"*{art.age_str}*"]
            if art.score:
                meta.append(f"pentest {art.score}/10")
            if art.cves:
                meta.append(" ".join(art.cves[:3]))
            lines.append(" · ".join(meta))
            if art.summary_fr:
                sfr = art.summary_fr if isinstance(art.summary_fr, str) else " ".join(art.summary_fr)
                lines.append(f"> 🇫🇷 {sfr}")
            if art.summary and not art.summary_fr:
                lines.append(f"> {art.summary}")
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
    print(c("bold", "\n═══ Daily Hacker News — Résumé ═══\n"))
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
            title = art.title[:62]
            print(f"    {c('grey', art.date_fmt)}  {c('orange',sev)}{kev}{expl}{score}  {title}")
            if art.summary_fr:
                sfr = art.summary_fr if isinstance(art.summary_fr, str) else " ".join(art.summary_fr)
                print(f"    {c('cyan','  → '+sfr[:80])}")
        if len(arts) > 5:
            print(f"    {c('grey', f'… +{len(arts)-5} autres')}")
        print()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Daily Hacker News — journal de veille sécurité / pentest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Exemples :
          python3 scripts/secjournal.py                      # 24h, HTML
          python3 scripts/secjournal.py --days 7             # semaine
          python3 scripts/secjournal.py --output both        # HTML + Markdown
          python3 scripts/secjournal.py --themes CVE,Exploit # thèmes ciblés
          python3 scripts/secjournal.py --max 30             # max 30/thème
          python3 scripts/secjournal.py --open               # ouvre le HTML
          python3 scripts/secjournal.py --export-opml        # exporte OPML
          python3 scripts/secjournal.py --no-fetch           # rss_watcher seul
          python3 scripts/secjournal.py --search "log4j"     # recherche (JSON)
        """),
    )
    ap.add_argument("--days",        type=int, default=1,
                    help="fenêtre temporelle en jours (défaut: 1)")
    ap.add_argument("--output",      choices=["html","md","both"], default="html",
                    help="format de sortie")
    ap.add_argument("--themes",      default="",
                    help="CSV de thèmes: CVE,Exploit,News-EN,News-FR,Outils,CTF")
    ap.add_argument("--max",         type=int, default=500,
                    help="articles conservés par thème (défaut: 500 = 10 pages × 50)")
    ap.add_argument("--per-page",    dest="per_page", type=int, default=50,
                    help="articles par page dans le HTML (défaut: 50)")
    ap.add_argument("--open",        dest="open", action="store_true", default=None,
                    help="ouvre le HTML dans le navigateur (défaut en .app)")
    ap.add_argument("--no-open",     dest="open", action="store_false",
                    help="ne pas ouvrir le HTML automatiquement")
    ap.add_argument("--export-opml", action="store_true",
                    help="exporte tous les feeds RSS en .opml")
    ap.add_argument("--no-fetch",    action="store_true",
                    help="n'utilise que les items de rss_watcher (sans refetch)")
    ap.add_argument("--workers",     type=int, default=12,
                    help="threads parallèles (défaut: 12)")
    ap.add_argument("--search",      default="",
                    help="mode recherche : interroge le store et sort du JSON (pour agents/scripts)")
    ap.add_argument("--limit",       type=int, default=50,
                    help="nombre max de résultats pour --search (défaut: 50)")
    args = ap.parse_args()

    if args.search:
        theme = args.themes.split(",")[0].strip() if args.themes.strip() else ""
        results = search_journal(args.search, limit=args.limit, theme=theme)
        print(json.dumps({"query": args.search, "count": len(results), "results": results},
                          ensure_ascii=False, indent=2))
        return

    if args.export_opml:
        p = OUT_DIR / "secjournal_feeds.opml"
        export_opml(p)
        print(f"{c('green','✓')} OPML → {p}")
        return

    theme_filter = {t.strip() for t in args.themes.split(",")} if args.themes.strip() else None
    cutoff       = datetime.now(timezone.utc) - timedelta(days=args.days)
    period       = f"{args.days}j" if args.days > 1 else "24h"

    # ── Sélection des feeds ───────────────────────────────────────────────────
    feeds = ALL_FEEDS
    if theme_filter:
        feeds = [f for f in feeds if f["theme"] in theme_filter]

    print(c("bold", f"\n🛡  Daily Hacker News · {period} · {len(feeds)} sources\n"))

    # ── Fetch parallèle ───────────────────────────────────────────────────────
    all_arts: list[Article] = []
    n_ok = 0

    if not args.no_fetch:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(fetch_feed, f, cutoff): f for f in feeds}
            for fut in as_completed(futures):
                feed = futures[fut]
                try:
                    arts = fut.result()
                    mark = c("green","✓") if arts else c("grey","○")
                    if arts:
                        n_ok += 1
                    all_arts.extend(arts)
                    print(f"  {mark} {feed['label']:<32} {len(arts):>3} articles")
                except Exception as e:
                    print(f"  {c('red','✗')} {feed['label']:<32} {e}")

    # ── Intégrer rss_watcher items (Ollama-enriched) ──────────────────────────
    rw_arts = load_rss_watcher_items(cutoff)
    if rw_arts:
        print(f"\n  {c('cyan','+')} rss_watcher: {len(rw_arts)} items Ollama chargés")
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

    total = sum(len(v) for v in by_theme.values())
    print(f"\n{c('bold','📊')} {total} articles uniques · {n_ok}/{len(feeds)} sources OK\n")

    n_store = persist_store(by_theme)
    print(f"{c('cyan','⛁')} store: {n_store} items indexés ({STORE})")

    print_summary(by_theme)

    # ── Génération des fichiers ───────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    html_path = None

    if args.output in ("html", "both"):
        html = render_html(by_theme, args, total, len(feeds), n_ok)
        html_path = OUT_DIR / f"secjournal_{ts}.html"
        html_path.write_text(html, encoding="utf-8")
        # Copier aussi OPML à côté
        opml_p = OUT_DIR / "secjournal_feeds.opml"
        if not opml_p.exists():
            export_opml(opml_p)
        print(f"{c('green','✓')} HTML  → {html_path}")

    if args.output in ("md", "both"):
        md   = render_md(by_theme, args, total)
        md_p = OUT_DIR / f"secjournal_{ts}.md"
        md_p.write_text(md, encoding="utf-8")
        print(f"{c('green','✓')} MD    → {md_p}")

    # Always generate feed.json for Garmin watch app
    json_str  = render_json(by_theme, args, total)
    json_path = OUT_DIR / "feed.json"
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
