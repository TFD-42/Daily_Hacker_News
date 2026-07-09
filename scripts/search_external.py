#!/usr/bin/env python3
"""
search_external.py — cross-platform open-source search adapters.

Each adapter returns a list of dicts with a common shape so results from
GitHub, Gitee (Chinese GitHub), GitLab, HuggingFace, Codeberg, etc. can
be aggregated, deduped by URL, sorted by score/date, and translated as a
single stream by `secjournal.py --search --sources ...`.

Result shape
------------
    {
      "source":       "github|gitee|gitlab|huggingface|codeberg",
      "kind":         "repo|code|issue|dataset|model|paper",
      "title":        "...",           # original language, kept as-is
      "url":          "...",
      "description":  "...",           # original language
      "stars":        <int|None>,
      "language":     "python|js|...", # source code language when known
      "lang":         "en|zh|...",     # human language guess of description
      "updated":      "2026-07-08T..." (ISO or empty),
      "author":       "user|org",
    }

Design notes
------------
- No hard third-party deps — stdlib only.
- All calls are best-effort: on network / auth / rate-limit failure the
  adapter returns [] and logs a note to stderr. The caller merges what it
  gets.
- Public endpoints only. Optional token env vars unlock higher rate limits
  (see per-adapter docs), never required to work.
- Language guess is heuristic (CJK block presence). Downstream translator
  decides whether to translate.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from typing import Optional

UA         = "DailyHackerNews/1.0"
_TIMEOUT   = 12
_CJK_RE    = None   # compiled on first use


def _http_get_json(url: str, headers: Optional[dict] = None,
                   timeout: int = _TIMEOUT) -> Optional[dict]:
    """GET + parse JSON, best-effort. Returns None on any failure."""
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read().decode("utf-8", errors="ignore")
        return json.loads(data)
    except urllib.error.HTTPError as e:
        print(f"[!] {url} → HTTP {e.code}", file=sys.stderr)
    except Exception as e:
        print(f"[!] {url} → {e}", file=sys.stderr)
    return None


def _guess_lang(text: str) -> str:
    """Very light language guess: 'zh' if any CJK codepoint, else 'en'."""
    global _CJK_RE
    if _CJK_RE is None:
        import re
        _CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
    text = text or ""
    return "zh" if _CJK_RE.search(text) else "en"


# ── GitHub ────────────────────────────────────────────────────────────────────

def search_github(query: str, limit: int = 20,
                  kinds: Optional[list[str]] = None) -> list[dict]:
    """Search GitHub.

    kinds: subset of {"repo","code","issue"} — default {"repo","issue"}.
    Auth: honours `GITHUB_TOKEN` env var to raise the 60/h anon rate limit
    to 5000/h. Never required.
    """
    kinds = kinds or ["repo", "issue"]
    headers = {"Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    per_kind = max(1, limit // len(kinds))
    out: list[dict] = []

    def _fetch(endpoint: str, qs: dict) -> Optional[dict]:
        url = f"https://api.github.com/search/{endpoint}?" + urllib.parse.urlencode(qs)
        return _http_get_json(url, headers=headers)

    if "repo" in kinds:
        d = _fetch("repositories", {"q": query, "per_page": per_kind,
                                     "sort": "updated"})
        for r in (d or {}).get("items", []) if d else []:
            desc = r.get("description") or ""
            out.append({
                "source":      "github",
                "kind":        "repo",
                "title":       r.get("full_name", ""),
                "url":         r.get("html_url", ""),
                "description": desc,
                "stars":       r.get("stargazers_count"),
                "language":    r.get("language") or "",
                "lang":        _guess_lang(desc + " " + (r.get("full_name") or "")),
                "updated":     r.get("updated_at") or "",
                "author":      (r.get("owner") or {}).get("login", ""),
            })

    if "issue" in kinds:
        d = _fetch("issues", {"q": query, "per_page": per_kind, "sort": "updated"})
        for r in (d or {}).get("items", []) if d else []:
            body = (r.get("body") or "")[:400]
            out.append({
                "source":      "github",
                "kind":        "issue",
                "title":       r.get("title", ""),
                "url":         r.get("html_url", ""),
                "description": body,
                "stars":       None,
                "language":    "",
                "lang":        _guess_lang((r.get("title") or "") + " " + body),
                "updated":     r.get("updated_at") or "",
                "author":      (r.get("user") or {}).get("login", ""),
            })

    if "code" in kinds:
        # code search REQUIRES auth. Skip when no token.
        if not tok:
            print("[i] github code search needs GITHUB_TOKEN — skipped",
                  file=sys.stderr)
        else:
            d = _fetch("code", {"q": query, "per_page": per_kind})
            for r in (d or {}).get("items", []) if d else []:
                out.append({
                    "source":      "github",
                    "kind":        "code",
                    "title":       f"{r.get('repository', {}).get('full_name', '')}/{r.get('path', '')}",
                    "url":         r.get("html_url", ""),
                    "description": "",
                    "stars":       None,
                    "language":    "",
                    "lang":        "en",
                    "updated":     "",
                    "author":      (r.get("repository", {}).get("owner") or {}).get("login", ""),
                })

    return out


# ── Gitee (Chinese GitHub) ───────────────────────────────────────────────────

def search_gitee(query: str, limit: int = 20) -> list[dict]:
    """Search Gitee, the biggest Chinese GitHub-alike. Public read API
    works without auth. `GITEE_TOKEN` env raises the rate limit.
    """
    headers = {}
    tok = os.environ.get("GITEE_TOKEN")
    qs = {"q": query, "per_page": max(1, min(limit, 50)),
          "sort": "stars_count", "order": "desc"}
    if tok:
        qs["access_token"] = tok
    url = "https://gitee.com/api/v5/search/repositories?" + urllib.parse.urlencode(qs)
    data = _http_get_json(url, headers=headers)
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for r in data:
        desc = r.get("description") or ""
        out.append({
            "source":      "gitee",
            "kind":        "repo",
            "title":       r.get("full_name", ""),
            "url":         r.get("html_url", ""),
            "description": desc,
            "stars":       r.get("stargazers_count"),
            "language":    r.get("language") or "",
            "lang":        _guess_lang(desc + " " + (r.get("full_name") or "")),
            "updated":     r.get("updated_at") or "",
            "author":      (r.get("owner") or {}).get("login", ""),
        })
    return out


# ── GitLab (gitlab.com) ──────────────────────────────────────────────────────

def search_gitlab(query: str, limit: int = 20) -> list[dict]:
    """Search public gitlab.com projects. `GITLAB_TOKEN` optional."""
    headers = {}
    tok = os.environ.get("GITLAB_TOKEN")
    if tok:
        headers["Private-Token"] = tok
    qs = {"search": query, "per_page": max(1, min(limit, 50)),
          "order_by": "last_activity_at"}
    url = "https://gitlab.com/api/v4/projects?" + urllib.parse.urlencode(qs)
    data = _http_get_json(url, headers=headers)
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for r in data:
        desc = r.get("description") or ""
        out.append({
            "source":      "gitlab",
            "kind":        "repo",
            "title":       r.get("path_with_namespace", ""),
            "url":         r.get("web_url", ""),
            "description": desc,
            "stars":       r.get("star_count"),
            "language":    "",
            "lang":        _guess_lang(desc + " " + (r.get("path_with_namespace") or "")),
            "updated":     r.get("last_activity_at") or "",
            "author":      (r.get("namespace") or {}).get("path", ""),
        })
    return out


# ── HuggingFace (models + datasets) ──────────────────────────────────────────

def search_huggingface(query: str, limit: int = 20) -> list[dict]:
    """Search HuggingFace models AND datasets. No auth required for
    public content. Returns both in one merged list."""
    out: list[dict] = []
    per = max(1, limit // 2)

    for kind, endpoint in (("model", "models"), ("dataset", "datasets")):
        qs = {"search": query, "limit": per, "sort": "downloads",
              "direction": "-1"}
        url = f"https://huggingface.co/api/{endpoint}?" + urllib.parse.urlencode(qs)
        data = _http_get_json(url)
        if not isinstance(data, list):
            continue
        for r in data:
            name = r.get("id") or r.get("modelId") or r.get("datasetId") or ""
            # cardData is frequently null on HF → guard before .get()
            card = r.get("cardData") or {}
            desc = (r.get("description") or card.get("description") or "")[:400]
            downloads = r.get("downloads")
            out.append({
                "source":      "huggingface",
                "kind":        kind,
                "title":       name,
                "url":         f"https://huggingface.co/{name}"
                               if kind == "model"
                               else f"https://huggingface.co/datasets/{name}",
                "description": desc,
                "stars":       downloads,   # downloads act as popularity signal
                "language":    "",
                "lang":        _guess_lang(desc + " " + name),
                "updated":     r.get("lastModified") or "",
                "author":      name.split("/")[0] if "/" in name else "",
            })
    return out


# ── Codeberg (Gitea) ─────────────────────────────────────────────────────────

def search_codeberg(query: str, limit: int = 20) -> list[dict]:
    """Search codeberg.org (a Gitea instance). Public, no auth."""
    qs = {"q": query, "limit": max(1, min(limit, 50)), "type": "repos"}
    url = "https://codeberg.org/api/v1/repos/search?" + urllib.parse.urlencode(qs)
    data = _http_get_json(url)
    if not isinstance(data, dict):
        return []
    out: list[dict] = []
    for r in data.get("data", []) or []:
        desc = r.get("description") or ""
        out.append({
            "source":      "codeberg",
            "kind":        "repo",
            "title":       r.get("full_name", ""),
            "url":         r.get("html_url", ""),
            "description": desc,
            "stars":       r.get("stars_count"),
            "language":    r.get("language") or "",
            "lang":        _guess_lang(desc + " " + (r.get("full_name") or "")),
            "updated":     r.get("updated_at") or "",
            "author":      (r.get("owner") or {}).get("login", ""),
        })
    return out


# ── Dispatch ─────────────────────────────────────────────────────────────────

ADAPTERS = {
    "github":      search_github,
    "gitee":       search_gitee,
    "gitlab":      search_gitlab,
    "huggingface": search_huggingface,
    "codeberg":    search_codeberg,
}


def search_all(query: str, sources: list[str], limit: int = 20) -> list[dict]:
    """Aggregate multiple adapters, dedup by URL, keep original order."""
    seen: set[str] = set()
    out:  list[dict] = []
    for s in sources:
        s = s.lower().strip()
        fn = ADAPTERS.get(s)
        if not fn:
            print(f"[!] unknown source: {s}", file=sys.stderr)
            continue
        try:
            for r in fn(query, limit=limit):
                url = r.get("url") or r.get("title", "")
                if url in seen:
                    continue
                seen.add(url)
                out.append(r)
        except Exception as e:
            print(f"[!] {s} failed: {e}", file=sys.stderr)
    return out


# CLI for standalone use / smoke tests
def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="cross-platform search adapters")
    ap.add_argument("query", nargs="+")
    ap.add_argument("--sources", default="github,gitee",
                    help="csv: github,gitee,gitlab,huggingface,codeberg")
    ap.add_argument("--limit",   type=int, default=10)
    args = ap.parse_args()
    q = " ".join(args.query)
    results = search_all(q, args.sources.split(","), limit=args.limit)
    print(json.dumps({"query": q, "sources": args.sources,
                      "count": len(results), "results": results},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
