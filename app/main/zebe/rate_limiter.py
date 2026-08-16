import time
import threading
from collections import defaultdict
from dataclasses import dataclass

WINDOW_SECONDS = 900
CLEANUP_INTERVAL = 1000


@dataclass
class _Entry:
    attempts: int = 0
    first_attempt: float = 0.0
    locked_until: float = 0.0


class RateLimiter:
    def __init__(self) -> None:
        self._store: defaultdict[str, _Entry] = defaultdict(_Entry)
        self._lock = threading.Lock()
        self._ops_since_cleanup = 0

    def is_blocked(self, key: str) -> tuple[bool, int]:
        with self._lock:
            self._ops_since_cleanup += 1
            if self._ops_since_cleanup >= CLEANUP_INTERVAL:
                self._prune_expired()
                self._ops_since_cleanup = 0

            entry = self._store.get(key)
            if entry is None:
                return False, 0

            now = time.monotonic()

            if entry.locked_until > 0:
                if now >= entry.locked_until:
                    del self._store[key]
                    return False, 0
                remaining = int(entry.locked_until - now)
                return True, remaining

            if entry.first_attempt > 0 and (now - entry.first_attempt) > WINDOW_SECONDS:
                del self._store[key]
                return False, 0

            return False, 0

    def record_failure(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            self._ops_since_cleanup += 1
            if self._ops_since_cleanup >= CLEANUP_INTERVAL:
                self._prune_expired()
                self._ops_since_cleanup = 0

            entry = self._store[key]
            if entry.attempts == 0:
                entry.first_attempt = now
            entry.attempts += 1

            if entry.attempts >= 15:
                entry.locked_until = now + 1800
            elif entry.attempts >= 10:
                entry.locked_until = now + 300
            elif entry.attempts >= 5:
                entry.locked_until = now + 60

            if entry.locked_until > 0:
                return int(entry.locked_until - now)
            return 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def _prune_expired(self) -> None:
        now = time.monotonic()
        stale = [
            k
            for k, e in self._store.items()
            if (e.locked_until > 0 and now >= e.locked_until)
            or (e.first_attempt > 0 and (now - e.first_attempt) > WINDOW_SECONDS)
        ]
        for k in stale:
            del self._store[k]


class Throttle:
    def __init__(self, max_ops: int, window_seconds: int) -> None:
        self._max_ops = max_ops
        self._window_seconds = window_seconds
        self._store: defaultdict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._ops_since_cleanup = 0

    def is_allowed(self, key: str) -> tuple[bool, int]:
        with self._lock:
            self._ops_since_cleanup += 1
            if self._ops_since_cleanup >= CLEANUP_INTERVAL:
                self._prune_expired()
                self._ops_since_cleanup = 0

            now = time.monotonic()
            window_start = now - self._window_seconds
            self._store[key] = [t for t in self._store[key] if t > window_start]
            count = len(self._store[key])
            if count >= self._max_ops:
                oldest = self._store[key][0]
                retry_after = int(oldest + self._window_seconds - now)
                return False, max(retry_after, 1)
            self._store[key].append(now)
            return True, self._max_ops - count - 1

    def _prune_expired(self) -> None:
        now = time.monotonic()
        window_start = now - self._window_seconds
        stale = [k for k, stamps in self._store.items() if not any(t > window_start for t in stamps)]
        for k in stale:
            del self._store[k]


auth_rate_limiter = RateLimiter()
invoice_throttle = Throttle(max_ops=50, window_seconds=3600)
