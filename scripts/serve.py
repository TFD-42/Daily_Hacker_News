#!/usr/bin/env python3
"""
serve.py — hardened static server for Daily Hacker News.

Serves ONLY the generated public site (`out/journals/site/*.html`,
`feed.json`, `secjournal_feeds.opml`). The server root is that dedicated
subdir, so every other path — source code, config, knowledge base, the
journals parent, Markdown, dotfiles, arbitrary directories — is physically
out of reach as well as denied by the filename whitelist.

Design principles
-----------------
- Whitelist by exact filename or extension. Deny by default.
- Canonicalise every requested path against the resolved allowed root:
  no `..`, no symlinks pointing outside, no absolute paths.
- No directory listing, ever.
- GET / HEAD only. Any other method → 405.
- Strong security headers on every 2xx response.
- HTTPS supported via `--cert` / `--key`.
- Optional HTTP Basic auth.
- Optional IP allowlist.
- Rate limit per remote IP (sliding-window log in memory).
- Structured request log to stdout (+ optional file).
- Graceful shutdown on SIGTERM / SIGINT.

Zero third-party deps — stdlib only.

Usage
-----
    python3 scripts/serve.py                                 # 0.0.0.0:8000 HTTP
    python3 scripts/serve.py --host 127.0.0.1                # local only
    python3 scripts/serve.py --port 8443 --cert c.pem --key k.pem   # HTTPS
    python3 scripts/serve.py --auth alice:s3cret             # basic auth
    python3 scripts/serve.py --allow 1.2.3.4 --allow 10.0.0.0/8

Env overrides: `DHN_HOST`, `DHN_PORT`, `DHN_AUTH`, `DHN_CERT`, `DHN_KEY`.
"""
from __future__ import annotations

import argparse
import base64
import hmac
import http.server
import ipaddress
import json
import os
import re
import signal
import socket
import socketserver
import ssl
import sys
import time
import urllib.parse
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

# ── Path resolution — mirrors secjournal.py so we work in dev + frozen ────────

def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        for p in Path(sys.executable).resolve().parents:
            if (p / "out" / "journals").is_dir() or (p / "scripts").is_dir():
                return p
    return Path(__file__).resolve().parents[1]

PROJECT_ROOT = _project_root()
# The server root is the dedicated public subdir `out/journals/site`, which
# holds ONLY servable artifacts (HTML, feed.json, OPML). The rest of the
# project — source, configs, knowledge base, the journals parent itself — is
# physically outside this root and therefore unreachable, independent of the
# filename whitelist below (defence in depth).
JOURNAL_DIR  = (PROJECT_ROOT / "out" / "journals" / "site").resolve()

# ── Whitelist — what may leave the server ────────────────────────────────────

ALLOWED_EXACT = {
    "feed.json",
    "secjournal_feeds.opml",
    "favicon.ico",   # tolerated, may 404 silently if absent
}
ALLOWED_EXT   = {".html"}
# Journal filenames look like `secjournal_YYYYMMDD_HHMM.html` — anchor to that.
JOURNAL_RE    = re.compile(r"^secjournal_\d{8}_\d{4}\.html$")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".opml": "text/xml; charset=utf-8",
    ".ico":  "image/x-icon",
}

# ── Security headers applied to every 2xx response ───────────────────────────

def base_headers(tls: bool) -> dict:
    h = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options":        "DENY",
        "Referrer-Policy":        "strict-origin-when-cross-origin",
        "Permissions-Policy":     "geolocation=(), camera=(), microphone=(), payment=()",
        "Cache-Control":          "public, max-age=60",
        # CSP: HTML has inline <style> and inline <script> for search/pagination.
        # No third-party origins, no eval. Adjust if you inline more.
        "Content-Security-Policy":
            "default-src 'none'; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "form-action 'none'; "
            "frame-ancestors 'none'; "
            "base-uri 'none'",
    }
    if tls:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return h

# ── Rate limiter ─────────────────────────────────────────────────────────────

class RateLimiter:
    """Simple sliding-window bucket. Per-IP, single-process. Not distributed."""
    def __init__(self, max_reqs: int, window_s: int):
        self.max = max_reqs
        self.win = window_s
        self.buckets: dict[str, deque] = {}
        self.lock = Lock()
        self._since_reap = 0

    def _reap(self, now: float) -> None:
        """Evict drained buckets so the dict can't grow unbounded across many
        distinct (or spoofed) source IPs. Amortised: runs every ~512 requests."""
        self._since_reap += 1
        if self._since_reap < 512:
            return
        self._since_reap = 0
        dead = [k for k, dq in self.buckets.items()
                if not dq or now - dq[-1] > self.win]
        for k in dead:
            del self.buckets[k]

    def allow(self, ip: str) -> bool:
        now = time.time()
        with self.lock:
            self._reap(now)
            q = self.buckets.get(ip)
            if q is None:
                q = deque()
                self.buckets[ip] = q
            # drop old
            while q and now - q[0] > self.win:
                q.popleft()
            if len(q) >= self.max:
                return False
            q.append(now)
            return True

# ── Server config (module-level, mutated by main) ────────────────────────────

class Cfg:
    tls          = False
    auth_header  = ""      # "Basic <base64(user:pass)>"; empty = no auth
    allow_nets: list[ipaddress._BaseNetwork] = []   # empty = anywhere
    limiter: Optional[RateLimiter] = None
    log_path: Optional[Path] = None
    trust_proxy  = False   # honour CF-Connecting-IP / X-Forwarded-For headers.
                           # Only enable when serving *behind* a trusted proxy
                           # (e.g. Cloudflare Tunnel). NEVER on a direct-internet
                           # server: any client can spoof those headers.

# ── Handler ──────────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "DailyHackerNews/1.0"
    sys_version    = ""    # hide Python version in Server header

    # -- helpers --------------------------------------------------------------

    def client_ip(self) -> str:
        """Real client IP. Honours proxy headers (Cloudflare, standard proxies).
        The Cloudflare-Access-Control gate ensures these only fire behind CF."""
        # priority: CF-Connecting-IP (Cloudflare) > X-Forwarded-For > direct
        cf = self.headers.get("CF-Connecting-IP")
        if cf and Cfg.trust_proxy:
            return cf.split(",")[0].strip()
        xff = self.headers.get("X-Forwarded-For")
        if xff and Cfg.trust_proxy:
            # Take the RIGHTMOST value — it is appended by the nearest (trusted)
            # proxy and reflects who actually connected to it. The leftmost
            # entries are client-supplied and therefore spoofable.
            return xff.split(",")[-1].strip()
        return self.client_address[0]

    @staticmethod
    def _parse_ua(ua: str) -> dict:
        """Very light UA parse — enough to spot who is knocking. No third-party dep.
        Returns {"os": ..., "browser": ..., "device": ...}."""
        u = (ua or "").lower()
        os_ = "unknown"
        # order matters: iOS/Android UAs mention "Mac OS X" / "Linux" too
        if   "iphone"        in u or "ipad" in u: os_ = "iOS"
        elif "android"       in u:      os_ = "Android"
        elif "windows nt 10" in u:      os_ = "Windows 10/11"
        elif "windows nt"    in u:      os_ = "Windows"
        elif "mac os x"      in u or "macintosh" in u: os_ = "macOS"
        elif "cros"          in u:      os_ = "ChromeOS"
        elif "linux"         in u:      os_ = "Linux"
        elif "freebsd"       in u:      os_ = "FreeBSD"

        br = "unknown"
        if   "edg/"     in u:           br = "Edge"
        elif "chrome/"  in u and "chromium" not in u: br = "Chrome"
        elif "chromium" in u:           br = "Chromium"
        elif "firefox/" in u:           br = "Firefox"
        elif "safari/"  in u and "chrome" not in u: br = "Safari"
        elif "curl/"    in u:           br = "curl"
        elif "wget/"    in u:           br = "wget"
        elif "python"   in u:           br = "python"
        elif "bot" in u or "crawler" in u or "spider" in u: br = "bot"

        device = "mobile" if "mobile" in u or "android" in u or "iphone" in u else \
                 "tablet" if "ipad"   in u or ("tablet" in u) else "desktop"
        return {"os": os_, "browser": br, "device": device}

    def _log(self, status: int, path: str, note: str = "") -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ua = self.headers.get("User-Agent", "-")[:200]
        parsed = self._parse_ua(ua)
        rec = {
            "t":       ts,
            "ip":      self.client_ip(),
            "raw_ip":  self.client_address[0],   # socket-level IP for audit
            "country": self.headers.get("CF-IPCountry", "-") if Cfg.trust_proxy else "-",
            "method":  self.command,
            "path":    path,
            "status":  status,
            "ref":     (self.headers.get("Referer") or "-")[:200],
            "ua":      ua,
            "os":      parsed["os"],
            "browser": parsed["browser"],
            "device":  parsed["device"],
        }
        if note:
            rec["note"] = note
        line = json.dumps(rec, ensure_ascii=False)
        print(line, flush=True)
        if Cfg.log_path:
            try:
                with Cfg.log_path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    def _send(self, status: int, body: bytes = b"",
              ctype: str = "text/plain; charset=utf-8",
              extra: Optional[dict] = None) -> None:
        self.send_response(status)
        for k, v in base_headers(Cfg.tls).items():
            self.send_header(k, v)
        self.send_header("Content-Type",   ctype)
        self.send_header("Content-Length", str(len(body)))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _deny(self, status: int, msg: str, path: str, note: str = "") -> None:
        self._send(status, msg.encode(),
                   extra={"WWW-Authenticate": 'Basic realm="Daily Hacker News"'}
                          if status == 401 else None)
        self._log(status, path, note)

    # -- gates ----------------------------------------------------------------

    def _ip_allowed(self) -> bool:
        if not Cfg.allow_nets:
            return True
        try:
            ip = ipaddress.ip_address(self.client_ip())
        except ValueError:
            return False
        return any(ip in net for net in Cfg.allow_nets)

    def _auth_ok(self) -> bool:
        if not Cfg.auth_header:
            return True
        # Constant-time compare so response timing can't leak the credential.
        return hmac.compare_digest(self.headers.get("Authorization", ""), Cfg.auth_header)

    # -- resolution -----------------------------------------------------------

    def _resolve(self, url_path: str) -> Optional[Path]:
        """Turn a URL path into a real file under JOURNAL_DIR, or None if denied."""
        p = urllib.parse.urlparse(url_path).path
        # decode percent-encoded, reject NUL bytes
        try:
            p = urllib.parse.unquote(p, errors="strict")
        except Exception:
            return None
        if "\x00" in p or "\r" in p or "\n" in p:
            return None

        # Root → latest journal
        if p in ("", "/"):
            return self._latest_journal()

        # Strip leading /, drop query, refuse tricks
        p = p.lstrip("/")
        if ".." in p.split("/") or p.startswith("/") or p.startswith("~"):
            return None
        name = os.path.basename(p)
        if p != name:
            # We only serve flat files at the root, no subdirs.
            return None

        # Whitelist match
        if name in ALLOWED_EXACT:
            candidate = JOURNAL_DIR / name
        elif Path(name).suffix.lower() in ALLOWED_EXT:
            # journal HTMLs must match the exact filename pattern
            if not JOURNAL_RE.match(name):
                return None
            candidate = JOURNAL_DIR / name
        else:
            return None

        # Canonicalise and re-check containment (defence in depth vs symlink races)
        try:
            real = candidate.resolve(strict=True)
        except (FileNotFoundError, RuntimeError):
            return None
        try:
            real.relative_to(JOURNAL_DIR)
        except ValueError:
            return None
        if not real.is_file():
            return None
        return real

    def _latest_journal(self) -> Optional[Path]:
        try:
            journals = [p for p in JOURNAL_DIR.iterdir()
                        if p.is_file() and JOURNAL_RE.match(p.name)]
        except FileNotFoundError:
            return None
        if not journals:
            return None
        journals.sort(key=lambda p: p.name, reverse=True)
        return journals[0]

    # -- entry points ---------------------------------------------------------

    def do_GET(self):    self._handle()
    def do_HEAD(self):   self._handle()
    def do_POST(self):   self._deny(405, "method not allowed", self.path)
    def do_PUT(self):    self._deny(405, "method not allowed", self.path)
    def do_DELETE(self): self._deny(405, "method not allowed", self.path)
    def do_PATCH(self):  self._deny(405, "method not allowed", self.path)

    def _handle(self):
        # 0. IP allowlist
        if not self._ip_allowed():
            return self._deny(403, "forbidden", self.path, "ip not allowed")

        # 1. Rate limit
        if Cfg.limiter and not Cfg.limiter.allow(self.client_ip()):
            return self._deny(429, "too many requests", self.path, "rate limit")

        # 2. Auth
        if not self._auth_ok():
            return self._deny(401, "authentication required", self.path, "no auth")

        # 3. Resolve
        real = self._resolve(self.path)
        if real is None:
            return self._deny(404, "not found", self.path, "denied by whitelist")

        # 4. Serve
        try:
            body = real.read_bytes()
        except Exception as e:
            return self._deny(500, "read error", self.path, f"read: {e}")
        ctype = MIME.get(real.suffix.lower(), "application/octet-stream")
        self._send(200, body, ctype=ctype)
        self._log(200, self.path)

    def log_message(self, fmt, *args):
        # silence the default noisy stderr log — we already emit JSON via _log
        pass


# ── Threaded server + graceful shutdown ──────────────────────────────────────

class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ── main ─────────────────────────────────────────────────────────────────────

def parse_allow(values: list[str]) -> list[ipaddress._BaseNetwork]:
    out = []
    for v in values:
        v = v.strip()
        if not v:
            continue
        try:
            out.append(ipaddress.ip_network(v, strict=False))
        except ValueError:
            print(f"[!] bad --allow value: {v}", file=sys.stderr)
    return out


def parse_auth(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if ":" not in v:
        print("[!] --auth expects user:password", file=sys.stderr)
        return ""
    return "Basic " + base64.b64encode(v.encode()).decode()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Hardened static server for Daily Hacker News.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--host", default=os.environ.get("DHN_HOST", "0.0.0.0"),
                    help="interface d'ecoute (defaut: 0.0.0.0). "
                         "127.0.0.1 = local uniquement.")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("DHN_PORT", "8000")))
    ap.add_argument("--cert", default=os.environ.get("DHN_CERT", ""),
                    help="chemin certificat TLS (PEM). Requiert --key.")
    ap.add_argument("--key",  default=os.environ.get("DHN_KEY", ""),
                    help="chemin cle privee TLS (PEM). Requiert --cert.")
    ap.add_argument("--auth", default=os.environ.get("DHN_AUTH", ""),
                    help="basic auth 'user:password' (optionnel)")
    ap.add_argument("--allow", action="append", default=[],
                    help="IP ou CIDR autorise (repetable). "
                         "Sans, tout le monde peut se connecter.")
    ap.add_argument("--rate-max", type=int, default=100,
                    help="max requetes par IP / fenetre (defaut: 100)")
    ap.add_argument("--rate-window", type=int, default=60,
                    help="fenetre du rate limit en secondes (defaut: 60)")
    ap.add_argument("--log", type=Path, default=None,
                    help="fichier de log JSONL (append). stdout dans tous les cas.")
    ap.add_argument("--trust-proxy", action="store_true",
                    help="honorer CF-Connecting-IP / X-Forwarded-For (proxy en amont). "
                         "N'active que derriere Cloudflare Tunnel ou reverse-proxy de confiance.")
    args = ap.parse_args()

    if not JOURNAL_DIR.is_dir():
        print(f"[!] journal dir absent: {JOURNAL_DIR}", file=sys.stderr)
        print("    run secjournal.py first to generate content.", file=sys.stderr)
        return 2

    if bool(args.cert) ^ bool(args.key):
        print("[!] --cert et --key doivent etre passes ensemble", file=sys.stderr)
        return 2

    Cfg.tls         = bool(args.cert and args.key)
    Cfg.auth_header = parse_auth(args.auth)
    Cfg.allow_nets  = parse_allow(args.allow)
    Cfg.limiter     = RateLimiter(args.rate_max, args.rate_window)
    Cfg.log_path    = args.log.resolve() if args.log else None
    Cfg.trust_proxy = args.trust_proxy

    # Serve.
    try:
        server = ThreadedServer((args.host, args.port), Handler)
    except OSError as e:
        print(f"[!] bind {args.host}:{args.port} failed: {e}", file=sys.stderr)
        return 3

    if Cfg.tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ctx.load_cert_chain(certfile=args.cert, keyfile=args.key)
        except Exception as e:
            print(f"[!] TLS load failed: {e}", file=sys.stderr)
            return 3
        # Modern-only defaults
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:!aNULL:!MD5:!SHA1")
        server.socket = ctx.wrap_socket(server.socket, server_side=True)

    scheme = "https" if Cfg.tls else "http"
    print(f"→ Daily Hacker News · {scheme}://{args.host}:{args.port}/", flush=True)
    print(f"  journals: {JOURNAL_DIR}", flush=True)
    print(f"  auth: {'yes' if Cfg.auth_header else 'no'} · "
          f"allowlist: {len(Cfg.allow_nets) or 'any IP'} · "
          f"rate: {args.rate_max}/{args.rate_window}s", flush=True)

    import threading
    def _shutdown(*_):
        print("\n→ shutdown…", flush=True)
        # server.shutdown() blocks until serve_forever exits; running it in
        # this thread would deadlock (we ARE the serve_forever thread when the
        # signal arrives). Kick it off in a helper thread so we can return.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
