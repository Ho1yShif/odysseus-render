# src/rate_limiter.py
"""Generic in-memory rate limiter — sliding window, keyed by IP.

Also owns ``trusted_client_ip``: the single, spoof-resistant way to derive the
client IP that every IP-keyed rate limiter in the app should share (demo caps and
the auth-route limiters alike). Keeping one helper + one env var here avoids two
limiters disagreeing about which ``X-Forwarded-For`` entry to trust.
"""

import logging
import os
import threading
import time
from typing import Dict, List

logger = logging.getLogger(__name__)


def _trusted_proxy_hops() -> int:
    """Number of trusted proxy hops in front of the app (see trusted_client_ip).

    Read per-call from ``TRUSTED_PROXY_HOPS`` (default 1, matching Render's single
    edge proxy) so tests and redeploys can retune it without a module reload.
    This mirrors the conventional trusted-hop count (Werkzeug ``ProxyFix``,
    uvicorn ``--forwarded-allow-ips``): ``n`` = ``n`` trusted proxies, and an
    explicit ``0`` = "no trusted proxy — the deploy is directly exposed, so
    ``X-Forwarded-For`` is entirely attacker-supplied and must be ignored in
    favour of the real TCP peer". Unset/invalid/negative falls back to 1 (the
    Render default). Only a deliberate ``0`` disables XFF parsing.
    """
    raw = os.getenv("TRUSTED_PROXY_HOPS", "").strip()
    if not raw:
        return 1
    try:
        val = int(raw)
    except ValueError:
        return 1
    return val if val >= 0 else 1


_logged_xff_sample = False
_xff_log_lock = threading.Lock()


def trusted_client_ip(request) -> str:
    """Return the spoof-resistant client IP for rate limiting behind Render.

    ``X-Forwarded-For`` is an ordered list; Render's edge proxy appends the real
    peer IP to the RIGHT, so the trustworthy client IP is ``TRUSTED_PROXY_HOPS``
    entries from the right. The leftmost entry is client-supplied and spoofable,
    so we must NOT read it. Falls back to the immediate peer (``request.client``)
    when the header is absent or shorter than the configured hop count.

    When ``TRUSTED_PROXY_HOPS`` is ``0`` (directly-exposed deploy with no trusted
    proxy), ``X-Forwarded-For`` is wholly attacker-supplied and is ignored: the
    key is always the real TCP peer. Forks deploying this template off Render must
    set ``0`` if the service is internet-facing with no proxy — leaving the
    default ``1`` there makes the rate limiter spoofable.

    NOTE: this assumes uvicorn runs WITHOUT ``--proxy-headers`` (see
    docker/entrypoint.render.sh), so ``request.client.host`` is the Render proxy
    and only the XFF right-side entry identifies the client. To confirm the hop
    count on a real deploy, this logs the raw header + resolved IP exactly ONCE at
    startup (grep the logs for ``[trusted-ip] X-Forwarded-For sample``); adjust
    ``TRUSTED_PROXY_HOPS`` if the resolved IP isn't the true client.
    """
    headers = getattr(request, "headers", None)
    xff = headers.get("x-forwarded-for", "") if headers else ""
    hops = _trusted_proxy_hops()
    resolved = ""
    if xff and hops > 0:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= hops:
            resolved = parts[-hops]
    if not resolved:
        resolved = request.client.host if getattr(request, "client", None) else ""

    # One-shot observability so the hop-count assumption can be verified against
    # real Render traffic without a redeploy. Only fires when an XFF is present.
    global _logged_xff_sample
    if xff and not _logged_xff_sample:
        with _xff_log_lock:
            if not _logged_xff_sample:
                _logged_xff_sample = True
                logger.info(
                    "[trusted-ip] X-Forwarded-For sample=%r hops=%s -> resolved=%r "
                    "(peer=%s). If resolved is not the true client IP, retune "
                    "TRUSTED_PROXY_HOPS.",
                    xff,
                    hops,
                    resolved,
                    request.client.host if getattr(request, "client", None) else "",
                )
    return resolved


class RateLimiter:
    """Sliding-window rate limiter.

    Usage:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        if not limiter.check(ip):
            raise HTTPException(429, "Too many requests")
    """

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._log: Dict[str, List[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = max(window_seconds * 2, 120)

    def check(self, key: str) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        now = time.monotonic()
        with self._lock:
            self._maybe_cleanup(now)
            timestamps = self._log.get(key, [])
            cutoff = now - self.window
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self.max_requests:
                self._log[key] = timestamps
                return False
            timestamps.append(now)
            self._log[key] = timestamps
            return True

    def _maybe_cleanup(self, now: float) -> None:
        """Periodically purge stale entries."""
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        cutoff = now - self.window
        stale = [k for k, v in self._log.items() if not v or v[-1] <= cutoff]
        for k in stale:
            del self._log[k]
