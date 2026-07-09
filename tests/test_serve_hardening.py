"""End-to-end tests of the hardened server whitelist + method + security headers."""
from __future__ import annotations

import http.client
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close()
    return p


class _ServerRunner:
    """Run serve.py's ThreadedServer in a thread against a temp journal dir."""

    def __init__(self, serve_mod, journal_dir: Path):
        self.mod  = serve_mod
        self.port = _free_port()
        # Wire the server's JOURNAL_DIR to our tmp
        serve_mod.JOURNAL_DIR = journal_dir.resolve()
        # Reset Cfg for clean state per test
        serve_mod.Cfg.tls         = False
        serve_mod.Cfg.auth_header = ""
        serve_mod.Cfg.allow_nets  = []
        serve_mod.Cfg.limiter     = serve_mod.RateLimiter(10_000, 60)
        serve_mod.Cfg.log_path    = None
        serve_mod.Cfg.trust_proxy = False

        self.server = serve_mod.ThreadedServer(("127.0.0.1", self.port), serve_mod.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                        kwargs={"poll_interval": 0.1}, daemon=True)

    def __enter__(self):
        self.thread.start()
        time.sleep(0.1)  # let bind settle
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method: str, path: str, headers: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), body


# ── whitelist ────────────────────────────────────────────────────────────────

def test_root_serves_latest_journal(serve_mod, tmp_journal_dir):
    with _ServerRunner(serve_mod, tmp_journal_dir) as srv:
        code, _, body = srv.request("GET", "/")
    assert code == 200
    assert b"demo" in body


def test_feed_json_served(serve_mod, tmp_journal_dir):
    with _ServerRunner(serve_mod, tmp_journal_dir) as srv:
        code, _, body = srv.request("GET", "/feed.json")
    assert code == 200
    assert b"items" in body


@pytest.mark.parametrize("bad_path", [
    "/.gitignore",
    "/scripts/serve.py",
    "/configs/feeds.yaml",
    "/hello.txt",
    "/secjournal_00000000_0000.html",   # correct pattern but file absent
    "/../scripts/serve.py",
    "/%2e%2e/scripts/serve.py",
    "/sub/secjournal_20260101_0000.html",  # subdir request
])
def test_blocked_paths_return_404(serve_mod, tmp_journal_dir, bad_path):
    with _ServerRunner(serve_mod, tmp_journal_dir) as srv:
        code, _, _ = srv.request("GET", bad_path)
    assert code == 404, f"path {bad_path!r} leaked (got {code})"


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_write_methods_return_405(serve_mod, tmp_journal_dir, method):
    with _ServerRunner(serve_mod, tmp_journal_dir) as srv:
        code, _, _ = srv.request(method, "/")
    assert code == 405


# ── security headers ─────────────────────────────────────────────────────────

def test_security_headers_present_on_200(serve_mod, tmp_journal_dir):
    with _ServerRunner(serve_mod, tmp_journal_dir) as srv:
        code, headers, _ = srv.request("GET", "/feed.json")
    assert code == 200
    lower = {k.lower(): v for k, v in headers.items()}
    for h in ("x-content-type-options", "x-frame-options",
              "referrer-policy", "content-security-policy",
              "permissions-policy"):
        assert h in lower, f"missing header: {h}"
    assert lower["x-frame-options"].lower() == "deny"


# ── proxy trust (CF-Connecting-IP / CF-IPCountry) ────────────────────────────

def test_proxy_headers_ignored_by_default(serve_mod, tmp_journal_dir):
    with _ServerRunner(serve_mod, tmp_journal_dir) as srv:
        # even if a client claims a CF-Connecting-IP, we shouldn't trust it
        assert not serve_mod.Cfg.trust_proxy
        code, _, _ = srv.request("GET", "/feed.json",
                                 headers={"CF-Connecting-IP": "203.0.113.42"})
    assert code == 200
