"""The auth-route rate limiters must key on the trusted client IP, not the
spoofable leftmost X-Forwarded-For — otherwise a client behind Render could mint
a fresh limiter bucket per request by rotating that header (the same bypass the
demo caps had). This exercises the /login limiter end to end.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from routes.auth_routes import setup_auth_routes, LoginRequest


def _login_endpoint(auth_manager):
    router = setup_auth_routes(auth_manager)
    for route in router.routes:
        if getattr(route, "path", None) == "/api/auth/login" and "POST" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError("login route not found")


def _req(spoof_left, real="198.51.100.9"):
    return SimpleNamespace(
        headers={"x-forwarded-for": f"{spoof_left}, {real}"},
        client=SimpleNamespace(host="10.0.0.1"),  # the Render proxy peer, shared by all
        cookies={},
    )


def _status(login, request, body, response):
    try:
        asyncio.run(login(body=body, request=request, response=response))
        return 200
    except Exception as exc:  # HTTPException
        return getattr(exc, "status_code", None)


def test_login_limiter_keys_on_trusted_ip_not_spoofed_leftmost(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    # Bad credentials so every allowed request falls through the limiter to a
    # 401 — the limiter runs BEFORE password verification.
    auth_manager = MagicMock()
    auth_manager.verify_password.return_value = False
    login = _login_endpoint(auth_manager)

    body = LoginRequest(username="attacker", password="nope")
    response = SimpleNamespace(set_cookie=lambda **kw: None)

    # The /login limiter allows 15 requests / 60s. Rotate the spoofable leftmost
    # entry every call while the trusted rightmost IP stays constant: the first
    # 15 must reach password verification (401); the 16th must be blocked (429)
    # because they share the one trusted-IP bucket — the spoof didn't reset it.
    statuses = [_status(login, _req(f"{i}.{i}.{i}.{i}"), body, response) for i in range(16)]
    assert statuses[:15] == [401] * 15, statuses
    assert statuses[15] == 429, statuses


def test_login_limiter_gives_distinct_real_clients_independent_buckets(monkeypatch):
    # The old code keyed on request.client.host, which behind Render is the proxy
    # IP shared by everyone — so two different real clients would drain one global
    # bucket. Keyed on the trusted XFF entry, each real client gets its own budget.
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    auth_manager = MagicMock()
    auth_manager.verify_password.return_value = False
    login = _login_endpoint(auth_manager)
    body = LoginRequest(username="attacker", password="nope")
    response = SimpleNamespace(set_cookie=lambda **kw: None)

    # Client A exhausts its 15-request budget.
    a = [_status(login, _req("x", real="203.0.113.10"), body, response) for _ in range(15)]
    assert a == [401] * 15, a
    # Client B (different real IP, same proxy peer) is unaffected — under the old
    # client.host keying this would already be 429.
    assert _status(login, _req("y", real="203.0.113.11"), body, response) == 401
