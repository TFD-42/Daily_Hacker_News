# Contributing to Daily Hacker News

Thanks for wanting to help! DHN aims to be the "boring, correct, safe"
security-intel aggregator — pull requests that make it more of that are
warmly welcomed.

## Quick start

```bash
git clone https://github.com/TFD-42/Daily_Hacker_News
cd Daily_Hacker_News
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,enrichment]'
pytest                    # should be all green
ruff check scripts tests
black --check scripts tests
```

## Development workflow

1. Fork → branch off `main`
2. Make your change with **tests**. No test = no merge. Coverage floor
   is 60% and rising.
3. Run the checks locally:
   ```
   pytest --cov=scripts --cov-report=term-missing
   ruff check scripts tests
   black scripts tests
   ```
4. Open a PR against `main`. Fill in the PR template. CI must be green.

## What we especially want

- **Feed fixes / additions** — dead URLs, better replacements,
  new high-signal sources. Include the current `--verify-feeds` output
  in your PR body.
- **Parser hardening** — feeds return weird XML; if you find something
  DHN can't parse, add the fixture in `tests/fixtures/` and a test.
- **Translation backend adapters** — new backends should implement the
  `_try_<name>(text, timeout, target)` signature and follow the cache
  pattern.
- **Docs** — architecture, deployment guides, screenshots. Docs PRs go
  straight to `main`.

## What we push back on

- Adding heavy dependencies (anything > 2 MB installed) without a strong
  case. DHN's calling card is "stdlib + PyYAML + feedparser".
- Feeds behind a login or paywall.
- Anything that would break the "serve only whitelisted files" guarantee
  in `scripts/serve.py`.
- Framework refactors ("let's port to FastAPI!") without a concrete
  problem being solved.

## Code style

- Line length **100**, enforced by black + ruff
- Type hints on public functions; **`from __future__ import annotations`** at
  the top of every module
- Docstrings on non-trivial functions; explain the *why* not the *what*
- Keep `scripts/secjournal.py` boring and stdlib-friendly — network
  code must have a timeout, file I/O must have `encoding="utf-8"`
- Never log secrets, IPs of trusted proxies as the "real IP" without
  `Cfg.trust_proxy`, or file contents

## Commit messages

Conventional Commits *not required*, but appreciated:

```
feat(feeds): add Anquanke Chinese security news
fix(serve): reject requests with %00 in path
docs(readme): add Docker deployment section
test(heat): cover future-dated articles
```

## Security issues

**Do not open a public issue.** See [SECURITY.md](SECURITY.md).

## Code of conduct

By participating you agree to abide by the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Legal

Contributions are accepted under the same **MIT license** as the
project. By opening a PR you certify you have the right to license
your contribution this way (Developer Certificate of Origin —
<https://developercertificate.org>).
