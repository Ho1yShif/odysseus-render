"""Tests for the RateLimiter — pure in-memory, no server needed."""
import time
from types import SimpleNamespace

import pytest

import src.rate_limiter as rl_mod
from src.rate_limiter import RateLimiter, trusted_client_ip


def _req(xff=None, peer="10.0.0.1"):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=peer) if peer is not None else None,
    )


class TestTrustedClientIP:
    def test_reads_rightmost_when_one_hop(self, monkeypatch):
        # Render appends the real peer to the RIGHT; leftmost is spoofable.
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        assert trusted_client_ip(_req("1.1.1.1, 198.51.100.9")) == "198.51.100.9"

    def test_spoofed_leftmost_is_ignored(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        real = "198.51.100.9"
        assert trusted_client_ip(_req(f"9.9.9.9, {real}")) == real
        assert trusted_client_ip(_req(f"8.8.8.8, 7.7.7.7, {real}")) == real

    def test_honours_multiple_hops(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
        # 2 trusted hops -> the entry 2 from the right is the client.
        assert trusted_client_ip(_req("client, proxyA, proxyB")) == "proxyA"

    def test_falls_back_to_peer_without_xff(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        assert trusted_client_ip(_req(xff=None, peer="192.0.2.5")) == "192.0.2.5"

    def test_falls_back_to_peer_when_xff_shorter_than_hops(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "3")
        assert trusted_client_ip(_req("1.1.1.1, 2.2.2.2", peer="192.0.2.7")) == "192.0.2.7"

    def test_invalid_or_negative_hops_falls_back_to_one(self, monkeypatch):
        for bad in ("-1", "abc", ""):
            monkeypatch.setenv("TRUSTED_PROXY_HOPS", bad)
            # hops floored to 1 -> still reads the rightmost, never the leftmost.
            assert trusted_client_ip(_req("1.1.1.1, 198.51.100.9")) == "198.51.100.9"

    def test_zero_hops_trusts_peer_and_ignores_xff(self, monkeypatch):
        # No trusted proxy (directly-exposed deploy): the whole XFF is
        # attacker-supplied, so we MUST key on the real TCP peer and ignore it.
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
        assert trusted_client_ip(_req("1.2.3.4", peer="192.0.2.5")) == "192.0.2.5"
        assert (
            trusted_client_ip(_req("9.9.9.9, 8.8.8.8", peer="192.0.2.5")) == "192.0.2.5"
        )

    def test_zero_hops_falls_back_to_peer_without_xff(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
        assert trusted_client_ip(_req(xff=None, peer="192.0.2.9")) == "192.0.2.9"

    def test_logs_xff_sample_once(self, monkeypatch, caplog):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        monkeypatch.setattr(rl_mod, "_logged_xff_sample", False)
        with caplog.at_level("INFO", logger="src.rate_limiter"):
            trusted_client_ip(_req("1.1.1.1, 198.51.100.9"))
            trusted_client_ip(_req("2.2.2.2, 203.0.113.4"))
        samples = [r for r in caplog.records if "X-Forwarded-For sample" in r.getMessage()]
        assert len(samples) == 1  # one-shot, so it can't spam the log per request


class TestRateLimiterAllow:
    def test_allows_under_limit(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        assert rl.check("ip1") is True
        assert rl.check("ip1") is True
        assert rl.check("ip1") is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            rl.check("ip1")
        assert rl.check("ip1") is False

    def test_different_keys_independent(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        assert rl.check("ip1") is True
        assert rl.check("ip2") is True
        assert rl.check("ip1") is False
        assert rl.check("ip2") is False


class TestRateLimiterExpiry:
    def test_window_expiry(self):
        rl = RateLimiter(max_requests=1, window_seconds=1)
        assert rl.check("ip1") is True
        assert rl.check("ip1") is False
        time.sleep(1.1)
        assert rl.check("ip1") is True


class TestRateLimiterCleanup:
    def test_cleanup_removes_stale_entries(self):
        rl = RateLimiter(max_requests=1, window_seconds=1)
        rl._cleanup_interval = 0  # Force cleanup on every check
        rl.check("ip1")
        assert "ip1" in rl._log
        time.sleep(1.1)
        rl.check("ip2")  # Triggers cleanup
        assert "ip1" not in rl._log
