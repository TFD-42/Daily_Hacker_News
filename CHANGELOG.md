# Changelog

All notable changes to Daily Hacker News. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `pyproject.toml` — installable via `pip install .` or `pip install -e '.[dev]'`
- `pytest` test suite (33 tests, all green) covering:
  - Heat scoring + trending correlation
  - Server whitelist, path traversal defence, security headers
  - Translation cache correctness + persistence
  - `feeds.yaml` schema, duplicate IDs, private-endpoint policy
- GitHub Actions CI: test matrix (Python 3.9–3.12 × macOS + Linux),
  ruff + black + bandit + gitleaks + smoke test
- `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`
- Issue / PR templates under `.github/`
- Editable `configs/feeds.yaml` with `--verify-feeds` diagnostic
- Cross-platform search (`scripts/search_external.py`) —
  GitHub, Gitee, GitLab, HuggingFace, Codeberg
- CN threat intel sources — Freebuf, Anquanke, XZ (Alibaba), SecWiki,
  Seebug Paper (Chinese full-text auto-translated to EN/FR)
- `News-CN` theme
- Hardened public server (`scripts/serve.py`) — whitelist, headers,
  TLS, rate limit, IP allowlist, HTTP Basic auth, structured JSON logs
- `serve.sh` launcher — fg/bg/daemon, macOS launchd install,
  Linux systemd unit dump, self-signed cert generation
- `build2.sh` — Cloudflare Quick Tunnel wrapper with enriched logs
  (country, OS, browser, device) via `CF-Connecting-IP` / `CF-IPCountry`
- `scripts/serve.py` `--trust-proxy` flag for reverse-proxy setups
- `build.py` — Termux (Android) install target, auto-detects `$TERMUX_VERSION`
- Auto Ollama setup on first `--translate` run (install → daemon →
  model pull), with `deep-translator` fallback
- Trending Now section (cross-source CVE correlation, KEV pinning,
  top-heat 24h)
- Heat score per article (`fresh × severity × KEV × exploit × weight`)
- `--verify-feeds`, `--search`, `--search-external`, `--lang en|fr`

### Changed
- Feeds list: 62 → 51 (11 known-dead URLs removed, 6 updated)
- Dead feed detection surfaces HTTP status per feed instead of silent 0
- `secjournal.py --search` results now include `heat`, `summary_en`,
  `summary_fr`, and searchable haystack across all three languages

### Fixed
- Ollama `_ollama_model_present` signature normalisation
- Server graceful shutdown deadlock (SIGTERM now returns in < 1s)
- HTML `.cs-en` styling to distinguish translated summaries
- Path resolution respects `PROJECT_ROOT` before falling back to bundle

### Security
- Replaced a legacy identifying User-Agent with a neutral `DailyHackerNews/1.0`
- Purged the old identifier from git history
- Server rejects `%00` and encoded path traversal
- No third-party runtime deps required — stdlib-only path works

## [0.4.0] — 2026-07-08

### Added
- Gold-now refocus: Threat Intelligence theme, ZDI, Reddit netsec / blueteamsec,
  HackerOne Hacktivity
- Auto FR → EN translation (Ollama > deep_translator > passthrough)
- `journal_store.jsonl` searchable backlog (5000 items cap)

## [0.3.0] — 2026-07-08

### Added
- `configs/pentest_references.yaml` — 10 offensive-security refs
  (Command Injection, LOLBins, Upload/Webshells)

## [0.2.0] — 2026-07-08

### Added
- README "Thanks" section with badges crediting
  [edoardottt/awesome-hacker-search-engines](https://github.com/edoardottt/awesome-hacker-search-engines)

## [0.1.0] — 2026-07-08

### Added
- Initial public release
- 36 RSS feeds across CVE, Exploit, News-EN, News-FR, Outils, CTF
- 569-entry OSINT search-engine catalogue (from
  awesome-hacker-search-engines, CC0-1.0)
- Themed HTML journal with search bar and pagination
- JSON API for downstream consumers
- macOS `.app` / Windows `.exe` / Linux binary via PyInstaller

[Unreleased]: https://github.com/TFD-42/Daily_Hacker_News/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/TFD-42/Daily_Hacker_News/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/TFD-42/Daily_Hacker_News/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/TFD-42/Daily_Hacker_News/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/TFD-42/Daily_Hacker_News/releases/tag/v0.1.0
