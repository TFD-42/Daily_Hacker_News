<!--
Thanks for the PR! A few checks before you hit "Create":
-->

## What & why

<!-- One paragraph. What does this change? Why is it worth doing? -->

## How

<!-- Key implementation choices, or "boring / follows existing pattern". -->

## Test plan

<!-- What did you run to convince yourself this is correct? -->
- [ ] `pytest` green locally
- [ ] `ruff check scripts tests` clean
- [ ] `black --check scripts tests` clean
- [ ] For feed changes: `python3 scripts/secjournal.py --verify-feeds` output attached
- [ ] For server changes: manual `curl` against `serve.py` covering the new path
- [ ] For CLI changes: `--help` reads cleanly

## Type of change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change (needs a bump to the major version)
- [ ] Docs / tests / CI only

## Screenshots (UI changes)

<!-- Not required, but nice for HTML changes. -->

## Related issues

<!-- "Fixes #123" or "Refs #123" -->

## Checklist

- [ ] I read [CONTRIBUTING.md](CONTRIBUTING.md)
- [ ] I added / updated tests
- [ ] I updated [CHANGELOG.md](CHANGELOG.md) under `## [Unreleased]`
- [ ] I did NOT include any personal paths, IPs, or identifiers
      (see [SECURITY.md](SECURITY.md))
