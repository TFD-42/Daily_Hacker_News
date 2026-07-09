"""RateLimiter correctness + the memory-eviction fix.

The limiter is a per-IP sliding-window log. Without eviction its bucket dict
would grow one entry per distinct (or spoofed) source IP forever; `_reap`
drains stale buckets so memory stays bounded.
"""
from __future__ import annotations


def test_enforces_max_per_window(serve_mod):
    rl = serve_mod.RateLimiter(max_reqs=3, window_s=60)
    assert [rl.allow("1.2.3.4") for _ in range(5)] == [True, True, True, False, False]
    # a different IP has its own independent budget
    assert rl.allow("5.6.7.8") is True


def test_reap_evicts_stale_buckets(serve_mod):
    rl = serve_mod.RateLimiter(max_reqs=1, window_s=0)  # everything is instantly stale
    # touch many distinct IPs; window_s=0 means each entry is stale on next tick
    for i in range(1100):  # crosses the ~512 reap threshold at least twice
        rl.allow(f"10.0.{i // 256}.{i % 256}")
    # the dict must not carry ~1100 entries — stale buckets were reaped
    assert len(rl.buckets) < 600, f"buckets grew unbounded: {len(rl.buckets)}"
