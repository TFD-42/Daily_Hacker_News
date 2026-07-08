# 🛡 Daily Hacker News

Aggregates **55 security / pentest / threat-intel** RSS feeds into a single
searchable HTML report — with a **🔥 Trending Now** section that surfaces
CVEs cited by multiple sources in the last 24h, per-article **heat scoring**
(freshness × severity × KEV × source weight), and **auto FR → EN translation**
of every summary.

Bundled with:
- 🎯 **Threat Intelligence** feed set (Google Project Zero, TAG, MSRC, Talos,
  Unit42, SentinelLabs, Volexity, Kaspersky Securelist, ESET WeLiveSecurity,
  Malwarebytes Labs, Sophos, Trend Micro Research, Google Security Blog)
- 🐛 **Bug bounty gold** (HackerOne Hacktivity, ZDI advisories)
- 🌐 **Community signal** (r/netsec, r/AskNetsec, r/blueteamsec)
- 🕵️ **569-entry OSINT search-engine catalogue** (from
  [edoardottt/awesome-hacker-search-engines](https://github.com/edoardottt/awesome-hacker-search-engines),
  CC0-1.0)
- 💥 **10 offensive-security references** (Command Injection, LOLBins,
  Upload/Webshells)

## Features

- 🔥 **Gold-now trending detection** — cross-source CVE correlation + fresh KEV pin + top-heat 24h
- 🌡 **Heat score** per article — `fresh × severity × KEV × exploit × source_weight`, exposed in JSON
- 🇬🇧 **Auto FR → EN translation** — Ollama first (local, private), then `deep_translator` (Google, no key); silent skip if neither available, JSONL cache to skip re-translations
- 🔎 Live search bar (title, source, CVE, tag, summary, EN + FR)
- 📖 50 items per page × 10 pages of history per theme (500/theme)
- 🧠 Persistent JSONL store — other agents can query the backlog
- 🎯 Themed sections: **Trending · CVE · Threat · Exploit · News EN/FR · Tools · CTF**
- 🖥 One-file build → `.app` / `.exe` / Linux binary (PyInstaller)

## Quick start

```bash
git clone https://github.com/TFD-42/Daily_Hacker_News.git
cd Daily_Hacker_News
python3 -m pip install feedparser PyYAML deep-translator   # all recommended
python3 scripts/secjournal.py --open                       # generate today's journal
```

### Enable local (private) translation via Ollama

```bash
ollama pull qwen2.5:3b            # small bilingual model, ~2 GB
export OLLAMA_TRANSLATE_MODEL=qwen2.5:3b   # override default
python3 scripts/secjournal.py     # Ollama beats deep_translator when reachable
```

## Usage

```bash
python3 scripts/secjournal.py                      # 24h window, HTML
python3 scripts/secjournal.py --days 7             # last 7 days
python3 scripts/secjournal.py --output both        # HTML + Markdown
python3 scripts/secjournal.py --themes CVE,Exploit # filter themes
python3 scripts/secjournal.py --per-page 100       # bigger pages
python3 scripts/secjournal.py --export-opml        # export all feeds as OPML
python3 scripts/secjournal.py --no-translate       # skip EN translation
python3 scripts/secjournal.py --no-trending        # skip Trending Now section
python3 scripts/secjournal.py --translate-max 200  # translate more per run
```

Each JSON record shipped to consumers now includes `heat` (float), `summary_en`,
and `summary_fr` alongside the original `summary` — downstream projects can
pick the language they need without a second translation pass.

### Search backend (for other agents / scripts)

CLI — JSON on stdout:

```bash
python3 scripts/secjournal.py --search "log4j rce" --limit 20
python3 scripts/secjournal.py --search "kev" --themes CVE
```

Python — direct import:

```python
import sys; sys.path.insert(0, "scripts")
from secjournal import search_journal
hits = search_journal("ransomware", limit=30, theme="News-EN")
```

Search runs against `knowledge/rss/journal_store.jsonl` (auto-populated on each
run, capped at 5000 items, dedup by URL).

## Configuration

- **`configs/feeds.yaml`** — the RSS source list. Add / remove / disable feeds
  without recompiling. Fields: `id`, `label`, `theme`, `url`, optional
  `ftype` (`json_kev` / `gh_md`) and `enabled: false`.
- **`configs/search_engines.yaml`** — 569 OSINT search engines in 28
  categories, ready to consume from any tool.
- **`configs/pentest_references.yaml`** — 10 curated offensive-security
  references (Command Injection, LOLBins, Upload/Webshells) with per-category
  notes on the most effective techniques.

## Build a native app

```bash
python3 build.py
```

Produces `DailyHackerNews.app` on macOS, `DailyHackerNews.exe` on Windows,
or `DailyHackerNews` + `.desktop` on Linux. Double-clicking runs the tool and
auto-opens the resulting HTML in your browser.

The frozen bundle reads `configs/` / `knowledge/` from the folder that
contains the executable (fallback to embedded data), so you can update sources
by editing `feeds.yaml` next to the binary — no rebuild required.

## Output layout

```
out/journals/
├── secjournal_YYYYMMDD_HHMM.html   # today's report
├── feed.json                       # machine-readable snapshot
└── secjournal_feeds.opml           # importable feed list
knowledge/rss/
└── journal_store.jsonl             # searchable backlog
```

## Optional inputs

If you also run [rss_watcher](https://github.com/) (Ollama-enriched summariser),
drop its `items.jsonl` at `knowledge/rss/items.jsonl` — Daily Hacker News picks
it up automatically for French summaries, severity, and pentest relevance
scores.

## Credits

- OSINT search-engine catalogue: [edoardottt/awesome-hacker-search-engines](https://github.com/edoardottt/awesome-hacker-search-engines) (CC0-1.0)
- Feed inspiration: CERT-FR, NVD, CISA KEV, CVEFeed, Exploit-DB, Packet Storm,
  The Hacker News, Bleeping Computer, PortSwigger Daily, SANS ISC, and many
  more — see `configs/feeds.yaml`.

## License

MIT — see [LICENSE](LICENSE).

---

## 🙏 Thanks

Huge thanks to **[@edoardottt](https://github.com/edoardottt)** — a large part
of this project's OSINT catalogue (`configs/search_engines.yaml`, 569 engines
across 28 categories) comes directly from the amazing
[awesome-hacker-search-engines](https://github.com/edoardottt/awesome-hacker-search-engines)
list, redistributed here under CC0-1.0. Go star the source ⭐

[![Awesome Hacker Search Engines](https://img.shields.io/badge/OSINT_sources-awesome--hacker--search--engines-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/edoardottt/awesome-hacker-search-engines)
[![GitHub Repo stars](https://img.shields.io/github/stars/edoardottt/awesome-hacker-search-engines?style=for-the-badge&logo=github&label=Give%20it%20a%20star&color=ffca28)](https://github.com/edoardottt/awesome-hacker-search-engines/stargazers)
[![License: CC0-1.0](https://img.shields.io/badge/License-CC0_1.0-lightgrey.svg?style=for-the-badge)](https://creativecommons.org/publicdomain/zero/1.0/)
