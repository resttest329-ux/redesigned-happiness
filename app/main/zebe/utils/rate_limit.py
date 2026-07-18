import logging
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Optional

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


class InMemoryRateLimiter:
    """Simple sliding-window rate limiter keyed by an arbitrary string.

    Not distributed. Intended as a lightweight defense-in-depth guardrail
    for a single-process deployment; behind a load balancer, prefer a
    shared store.
    """

    def __init__(self):
        self._buckets: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def prune(self, max_entries: int = 10000) -> None:
        with self._lock:
            if len(self._buckets) <= max_entries:
                return
            now = time.monotonic()
            for k in list(self._buckets.keys()):
                dq = self._buckets[k]
                while dq and dq[0] < now - 3600:
                    dq.popleft()
                if not dq:
                    del self._buckets[k]


_limiter = InMemoryRateLimiter()


def _client_ip(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip() or "unknown"
        client = request.client
        if client and client.host:
            return client.host
    except Exception:
        logger.exception("rate_limit: failed to extract client ip")
    return "unknown"


def enforce(
    request: Optional[Request],
    bucket: str,
    *,
    limit: int,
    window_seconds: float,
    extra_key: str = "",
) -> None:
    """Raise HTTP 429 if the caller exceeds the given limit for this bucket."""
    ip = _client_ip(request)
    key = f"{bucket}:{ip}"
    if extra_key:
        key = f"{key}:{extra_key}"
    if not _limiter.check(key, limit, window_seconds):
        logger.warning(
            "rate_limit: bucket=%s ip=%s extra=%s over limit (%d/%.0fs)",
            bucket,
            ip,
            (extra_key[:16] + "…") if len(extra_key) > 16 else extra_key,
            limit,
            window_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down and try again shortly.",
            headers={"Retry-After": str(int(window_seconds))},
        )
    _limiter.prune()
