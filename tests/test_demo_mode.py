"""Demo mode — unit coverage for the DEMO-flag public chat showcase.

These exercise the choke points src/demo.py owns plus the two cross-module
hooks that must fire only for demo owners: the ephemeral-history persist skip
(SessionManager) and the least-privilege profile (AuthManager). Everything runs
with DEMO forced on via importlib.reload so the module-level flag reflects it.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def demo(monkeypatch):
    """Reload src.demo with DEMO=true so DEMO_MODE and the limiter are live."""
    monkeypatch.setenv("DEMO", "true")
    monkeypatch.setenv("DEMO_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("DEMO_RATE_LIMIT_PER_MINUTE", "10")
    monkeypatch.setenv("DEMO_MAX_MESSAGES_PER_SESSION", "3")
    monkeypatch.setenv("DEMO_MAX_OUTPUT_TOKENS", "512")
    import src.demo as d
    d = importlib.reload(d)
    yield d
    # Restore module to the ambient env for other tests.
    importlib.reload(d)


# --- identity ---------------------------------------------------------------
def test_is_demo_owner_matches_prefix_not_reserved_sentinel(demo):
    assert demo.is_demo_owner("demo-" + "a" * 32) is True
    # The literal reserved username must NOT be treated as a demo owner.
    assert demo.is_demo_owner("demo") is False
    assert demo.is_demo_owner("admin") is False
    assert demo.is_demo_owner("") is False
    assert demo.is_demo_owner(None) is False


def test_is_demo_owner_inert_when_demo_disabled(monkeypatch):
    """A ``demo-`` username on a non-demo deploy must be an ordinary user, not
    silently locked into the demo profile (is_demo_owner is gated on DEMO_MODE)."""
    monkeypatch.setenv("DEMO", "false")
    import src.demo as d
    d = importlib.reload(d)
    try:
        assert d.is_demo_owner("demo-" + "a" * 32) is False
    finally:
        importlib.reload(d)


# --- route whitelist --------------------------------------------------------
def test_route_whitelist_allows_only_the_chat_surface(demo):
    assert demo.is_demo_allowed("GET", "/") is True
    assert demo.is_demo_allowed("GET", "/api/default-chat") is True
    assert demo.is_demo_allowed("POST", "/api/session") is True
    assert demo.is_demo_allowed("POST", "/api/chat_stream") is True
    assert demo.is_demo_allowed("GET", "/static/app.js") is True
    # Everything dangerous stays off the whitelist.
    for method, path in [
        ("GET", "/api/tasks"),
        ("GET", "/api/assistant"),
        ("POST", "/api/mcp/servers"),
        ("POST", "/api/shell"),
        ("POST", "/api/upload"),
        ("GET", "/api/auth/settings"),  # handled as auth-exempt upstream, not here
        ("DELETE", "/api/session"),     # wrong method for a whitelisted path
    ]:
        assert demo.is_demo_allowed(method, path) is False, (method, path)


# --- cookie / owner minting -------------------------------------------------
def test_resolve_demo_owner_mints_then_reuses(demo):
    no_cookie = SimpleNamespace(cookies={})
    owner, new = demo.resolve_demo_owner(no_cookie)
    assert owner.startswith("demo-")
    assert new is not None and len(new) == 32
    # A returning visitor with a well-formed cookie keeps their owner, no re-mint.
    returning = SimpleNamespace(cookies={demo.DEMO_COOKIE: new})
    owner2, new2 = demo.resolve_demo_owner(returning)
    assert owner2 == owner
    assert new2 is None
    # A malformed cookie is rejected and a fresh id is minted.
    junk = SimpleNamespace(cookies={demo.DEMO_COOKIE: "not-a-valid-token"})
    owner3, new3 = demo.resolve_demo_owner(junk)
    assert new3 is not None and owner3 != owner


# --- output-token clamp -----------------------------------------------------
def test_clamp_output_tokens_never_uncapped(demo):
    cap = demo.DEMO_MAX_OUTPUT_TOKENS
    assert demo.clamp_demo_output_tokens(0) == cap       # 0 == "no cap" downstream
    assert demo.clamp_demo_output_tokens(None) == cap
    assert demo.clamp_demo_output_tokens(10_000) == cap  # over cap -> clamped
    assert demo.clamp_demo_output_tokens(100) == 100     # under cap -> kept


def test_output_token_floor_when_env_zero(monkeypatch):
    # An explicit 0 / negative output cap must fall back to a positive floor —
    # never "unlimited".
    monkeypatch.setenv("DEMO", "true")
    monkeypatch.setenv("DEMO_MAX_OUTPUT_TOKENS", "0")
    import src.demo as d
    d = importlib.reload(d)
    try:
        assert d.DEMO_MAX_OUTPUT_TOKENS > 0
    finally:
        importlib.reload(d)


# --- per-session message cap ------------------------------------------------
def test_message_cap_trips_after_limit(demo):
    owner = "demo-" + "b" * 32
    # Rate limit is 10/min so the first calls pass on that axis; cap is 3.
    seen = [demo.check_demo_limits(owner, "1.2.3.4") for _ in range(3)]
    assert seen == [None, None, None]
    tripped = demo.check_demo_limits(owner, "1.2.3.4")
    assert tripped == demo.LIMIT_MESSAGE


def test_rate_limit_trips_independently(monkeypatch):
    monkeypatch.setenv("DEMO", "true")
    monkeypatch.setenv("DEMO_RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("DEMO_MAX_MESSAGES_PER_SESSION", "0")  # disable msg cap
    import src.demo as d
    d = importlib.reload(d)
    try:
        owner = "demo-" + "c" * 32
        assert d.check_demo_limits(owner, "9.9.9.9") is None
        assert d.check_demo_limits(owner, "9.9.9.9") is None
        assert d.check_demo_limits(owner, "9.9.9.9") == d.LIMIT_MESSAGE
    finally:
        importlib.reload(d)


# --- rate limit keyed on IP, not owner (cookieless-flood bypass) ------------
def test_rate_limit_keyed_on_ip_survives_owner_churn(monkeypatch):
    # The bypass: a client that ignores Set-Cookie gets a fresh demo-<uuid>
    # owner on every request. Keying the limiter on owner|ip meant the sliding
    # window never filled. Keyed on IP alone, owner churn can't reset it.
    monkeypatch.setenv("DEMO", "true")
    monkeypatch.setenv("DEMO_RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch.setenv("DEMO_MAX_MESSAGES_PER_SESSION", "0")      # isolate the rate axis
    monkeypatch.setenv("DEMO_MAX_MESSAGES_PER_IP_PER_DAY", "0")   # isolate the rate axis
    import src.demo as d
    d = importlib.reload(d)
    try:
        ip = "203.0.113.7"
        # Each call is a brand-new cookieless owner — the exact bypass vector.
        results = [d.check_demo_limits("demo-" + f"{i:032x}", ip) for i in range(3)]
        assert results == [None, None, None]
        assert d.check_demo_limits("demo-" + "f" * 32, ip) == d.LIMIT_MESSAGE
    finally:
        importlib.reload(d)


# --- trusted client IP resolution (spoof resistance, Task 1a) ---------------
def test_demo_client_ip_reads_trusted_right_side_not_spoofable_left(demo):
    # Render appends the real peer IP to the RIGHT of X-Forwarded-For; the
    # leftmost entry is attacker-controlled. With one trusted hop (the default)
    # we must read the rightmost entry, so a rotating leftmost can't move the key.
    real = "198.51.100.9"
    req1 = SimpleNamespace(
        headers={"x-forwarded-for": f"1.1.1.1, {real}"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    req2 = SimpleNamespace(
        headers={"x-forwarded-for": f"2.2.2.2, 3.3.3.3, {real}"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert demo.demo_client_ip(req1) == real
    assert demo.demo_client_ip(req2) == real


def test_demo_client_ip_falls_back_to_peer_when_no_xff(demo):
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="192.0.2.5"))
    assert demo.demo_client_ip(req) == "192.0.2.5"


def test_spoofed_leftmost_xff_does_not_reset_rate_limit(monkeypatch):
    monkeypatch.setenv("DEMO", "true")
    monkeypatch.setenv("DEMO_RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch.setenv("DEMO_MAX_MESSAGES_PER_SESSION", "0")
    monkeypatch.setenv("DEMO_MAX_MESSAGES_PER_IP_PER_DAY", "0")
    import src.demo as d
    d = importlib.reload(d)
    try:
        real = "198.51.100.9"

        def send(spoof, owner):
            req = SimpleNamespace(
                headers={"x-forwarded-for": f"{spoof}, {real}"},
                client=SimpleNamespace(host="10.0.0.1"),
            )
            return d.check_demo_limits(owner, d.demo_client_ip(req))

        # Rotate both the spoofed leftmost XFF and the cookieless owner.
        outs = [send(f"{i}.{i}.{i}.{i}", "demo-" + f"{i:032x}") for i in range(1, 4)]
        assert outs == [None, None, None]
        assert send("9.9.9.9", "demo-" + "a" * 32) == d.LIMIT_MESSAGE
    finally:
        importlib.reload(d)


# --- per-IP daily ceiling (the real backstop, Task 2) -----------------------
def test_per_ip_daily_ceiling_trips_regardless_of_owner(monkeypatch):
    monkeypatch.setenv("DEMO", "true")
    monkeypatch.setenv("DEMO_RATE_LIMIT_PER_MINUTE", "0")        # isolate the per-IP axis
    monkeypatch.setenv("DEMO_MAX_MESSAGES_PER_SESSION", "0")
    monkeypatch.setenv("DEMO_MAX_MESSAGES_PER_IP_PER_DAY", "3")
    import src.demo as d
    d = importlib.reload(d)
    try:
        ip = "203.0.113.50"
        outs = [d.check_demo_limits("demo-" + f"{i:032x}", ip) for i in range(3)]
        assert outs == [None, None, None]
        # 4th request from a fresh owner still trips — the IP is the trusted key.
        assert d.check_demo_limits("demo-" + "b" * 32, ip) == d.LIMIT_MESSAGE
        # A different IP is unaffected.
        assert d.check_demo_limits("demo-" + "c" * 32, "203.0.113.99") is None
    finally:
        importlib.reload(d)


# --- pinned session config (env key, never persisted) -----------------------
def test_apply_demo_session_config_pins_model_and_env_key(demo, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-xyz")
    sess = SimpleNamespace(endpoint_url="https://evil/x", model="gpt-4-turbo", headers={})
    demo.apply_demo_session_config(sess)
    assert sess.model == demo.DEMO_MODEL
    assert sess.endpoint_url == demo.OPENAI_CHAT_URL
    assert sess.headers == {"Authorization": "Bearer sk-live-xyz"}


def test_apply_demo_session_config_no_key_is_safe(demo, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    sess = SimpleNamespace(endpoint_url="", model="", headers={"x": "y"})
    demo.apply_demo_session_config(sess)
    # No partial/leaked auth header when the server has no key.
    assert sess.headers == {}
    assert sess.model == demo.DEMO_MODEL


# --- privileges choke point (AuthManager.get_privileges) --------------------
def test_get_privileges_returns_locked_profile_for_demo_owner(demo):
    from core.auth import AuthManager
    # The demo branch returns before self.users is touched, so a bare instance
    # is enough — no config needed.
    am = AuthManager.__new__(AuthManager)
    privs = am.get_privileges("demo-" + "d" * 32)
    # Every spend / escalation surface is off.
    for off in (
        "can_use_agent", "can_use_browser", "can_use_bash", "can_use_documents",
        "can_use_research", "can_generate_images", "can_manage_memory",
    ):
        assert privs[off] is False, off
    assert privs["allowed_models"] == [demo.DEMO_MODEL]
    assert privs["allowed_models_restricted"] is True


def test_get_privileges_fails_closed_when_demo_import_raises(monkeypatch):
    # Defense-in-depth (Task 3): if src.demo can't be imported at the choke
    # point, a demo owner must NOT fall through to the more-permissive
    # DEFAULT_PRIVILEGES. The demo- prefix is detected inline and the locked-down
    # fallback profile is returned instead. No `demo` fixture here: patching
    # sys.modules["src.demo"] would break that fixture's reload-based teardown.
    import sys
    from core.auth import AuthManager

    class _Boom:
        def __getattr__(self, name):
            raise ImportError("simulated src.demo import failure")

    monkeypatch.setitem(sys.modules, "src.demo", _Boom())
    am = AuthManager.__new__(AuthManager)
    privs = am.get_privileges("demo-" + "d" * 32)
    for off in (
        "can_use_agent", "can_use_browser", "can_use_bash", "can_use_documents",
        "can_use_research", "can_generate_images", "can_manage_memory",
    ):
        assert privs[off] is False, off


# --- ephemeral history (SessionManager._persist_message skip) ---------------
def test_persist_message_skipped_for_demo_owner(demo, monkeypatch):
    import core.session_manager as SM
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        owner="demo-" + "e" * 32
    )
    monkeypatch.setattr(SM, "SessionLocal", MagicMock(return_value=db))

    manager = SM.SessionManager.__new__(SM.SessionManager)
    manager.sessions = {"sid": SimpleNamespace(history=[])}
    from core.models import ChatMessage
    manager._persist_message("sid", ChatMessage("user", "secret demo chat"))

    # Nothing written to disk for a demo owner.
    db.add.assert_not_called()
    db.commit.assert_not_called()


# --- composer bootstrap (GET /api/default-chat) -----------------------------
def _demo_default_chat_client(current_user):
    """Mount the model router with a middleware that authenticates every request
    as ``current_user`` (a demo owner), matching what the real AuthMiddleware
    sets for a demo visitor. The demo branch of get_default_chat returns before
    any DB/settings access, so a MagicMock discovery is enough."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.model_routes import setup_model_routes

    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = current_user
        request.state.is_demo = True
        return await call_next(request)

    app.include_router(setup_model_routes(MagicMock()))
    return TestClient(app)


def test_default_chat_returns_pinned_demo_config_for_demo_visitor(demo, monkeypatch):
    # Regression: a demo visitor owns no endpoints and has no prefs, so the
    # owner-scoped resolution returned {} and the composer showed "No chat
    # session active". The demo branch must hand back the pinned demo pair so
    # the frontend can create the session (apply_demo_session_config then
    # overrides it to the env key on read).
    client = _demo_default_chat_client("demo-" + "f" * 32)
    body = client.get("/api/default-chat").json()
    assert body["endpoint_url"] == demo.OPENAI_CHAT_URL
    assert body["model"] == demo.DEMO_MODEL


# --- session creation (POST /api/session) -----------------------------------
def test_create_session_pins_demo_config_and_discards_client_url(demo, monkeypatch):
    # A demo owner is a non-admin, so the raw-URL SSRF guard would 403 the
    # composer's POST /api/session (which sends a raw endpoint_url, no
    # endpoint_id) and the demo could never create a session. The demo branch
    # must skip that guard AND overwrite whatever URL the client posted with the
    # trusted pinned pair, so a hostile demo client can't steer the server at a
    # raw internal URL either.
    import routes.session_routes as sr
    from unittest.mock import MagicMock

    demo_owner = "demo-" + "a" * 32
    monkeypatch.setattr(sr, "effective_user", lambda request: demo_owner)

    created = SimpleNamespace(name="demo chat", headers={})
    sm = MagicMock()
    sm.create_session.return_value = created

    router = sr.setup_session_routes(sm, {})
    # session_routes uses a module-level APIRouter, so every setup call appends
    # to the same shared route list. Take the LAST /api/session POST — the one
    # this call just registered, bound to our `sm` — not a stale one another
    # test left behind.
    create = next(
        r.endpoint for r in reversed(router.routes)
        if getattr(r, "path", "") == "/api/session"
        and "POST" in getattr(r, "methods", set())
    )

    request = SimpleNamespace(state=SimpleNamespace(current_user=demo_owner, is_demo=True))
    # Client posts a raw internal URL with no endpoint_id — exactly the shape
    # the raw-URL guard is built to reject for non-admins.
    resp = create(
        request=request,
        name="demo chat",
        endpoint_url="http://169.254.169.254/latest/meta-data",
        model="gpt-4-turbo",
        rag=None,
        skip_validation=None,
        api_key="",
        endpoint_id="",
    )

    # No 403, and the SSRF URL was discarded in favor of the pinned demo pair.
    assert resp.model == demo.DEMO_MODEL
    _, kwargs = sm.create_session.call_args
    assert kwargs["endpoint_url"] == demo.OPENAI_CHAT_URL
    assert kwargs["model"] == demo.DEMO_MODEL
