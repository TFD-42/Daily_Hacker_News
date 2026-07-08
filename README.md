# 🛡 Daily Hacker News

Aggregates dozens of security / pentest RSS feeds into a single clean HTML
report — searchable, paginated, and exposed as a JSON API that other tools
can query.

Bundled with a **569-entry OSINT search-engine catalogue** (from
[edoardottt/awesome-hacker-search-engines](https://github.com/edoardottt/awesome-hacker-search-engines),
CC0-1.0) — Shodan, Censys, GreyNoise, ONYPHE and hundreds more, organised in
28 categories.

## Features

- 🔎 Live search bar (title, source, CVE, tag, summary)
- 📖 50 items per page × 10 pages of history per theme (500/theme)
- 🧠 Persistent JSONL store — other agents/scripts can query the backlog
- 🇫🇷 Optional French summaries via [rss_watcher](https://github.com/) items file
- 🎯 Themed sections: CVE, Exploits, Security News EN/FR, Tools, CTF
- 🖥 One-file build → `.app` / `.exe` / Linux binary (PyInstaller)

## Quick start

```bash
git clone https://github.com/<your-user>/Daily_Hacker_News.git
cd Daily_Hacker_News
python3 -m pip install feedparser PyYAML   # both optional but recommended
python3 scripts/secjournal.py --open       # generate today's journal
```

## Usage

```bash
python3 scripts/secjournal.py                      # 24h window, HTML
python3 scripts/secjournal.py --days 7             # last 7 days
python3 scripts/secjournal.py --output both        # HTML + Markdown
python3 scripts/secjournal.py --themes CVE,Exploit # filter themes
python3 scripts/secjournal.py --per-page 100       # bigger pages
python3 scripts/secjournal.py --export-opml        # export all feeds as OPML
```

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
