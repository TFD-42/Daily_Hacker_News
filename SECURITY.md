# Security Policy

## Supported Versions

Only the latest `main` branch is actively maintained. Tagged releases
receive security fixes on a best-effort basis for 90 days after the next
release supersedes them.

| Version | Supported          |
|---------|--------------------|
| `main`  | ✅                  |
| `0.5.x` | ✅ (90 days)        |
| < 0.5   | ❌                  |

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security problems.**

Instead:

1. Use GitHub's private vulnerability report:
   <https://github.com/TFD-42/Daily_Hacker_News/security/advisories/new>
2. Or, if that's unavailable, open an issue titled `SECURITY: contact needed`
   with **no details**, and the maintainer will reply with a private channel.

Please include:

- Affected version / commit
- Reproduction steps or PoC
- Impact assessment (data leak? RCE? auth bypass?)
- Suggested remediation, if any

We aim to acknowledge within **72 hours**, assess within **7 days**, and
ship a fix within **30 days** for CVSS 7.0+ issues.

## Scope

In scope:

- The Python code shipped in `scripts/`, `build.py`, and the shell
  wrappers (`serve.sh`, `build2.sh`)
- The `configs/*.yaml` catalogs (misinformation / poisoning risks)
- The hardened HTTP server (`scripts/serve.py`) — the whitelist,
  path canonicalisation, security headers, and rate limiter
- Documentation that could mislead a user into an insecure setup

Out of scope:

- Third-party feed sources aggregated by DHN (report to those sources
  directly)
- Cloudflare Quick Tunnel abuse (report to Cloudflare)
- Ollama or `deep_translator` upstream vulnerabilities (report upstream)
- Anything requiring physical access to the machine running DHN

## Threat Model

DHN is designed to be safe under the assumption that:

- The **operator** may be running behind a Cloudflare Tunnel or LAN
- The **feed sources** are untrusted (may serve malicious content —
  DHN escapes rendered HTML and never executes fetched content)
- The **public visitors** to a published journal only get to read the
  whitelisted HTML/JSON/OPML — no source code, no configs, no dotfiles
- The **operator's local machine** is trusted

## Bounty

We currently do not run a bug bounty. High-quality reports will be
credited in the `CHANGELOG.md` under `Security` unless the reporter
prefers anonymity.
