"""In-process token-bucket rate limiting.

Two policies are enforced by :class:`RateLimitMiddleware`:

* authenticated order mutations: 50 requests/second per API key/bearer token
* public prediction-market reads:  100 requests/minute per client IP

For a multi-process deployment the buckets are trivially replaceable with a
Redis ``INCR``/``EXPIRE`` implementation behind the same ``allow`` interface.
"""
from __future__ import annotations

import threading
import time


class TokenBucketLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, rate: float, capacity: float) -> tuple[bool, float]:
        """Consume one token.

        Returns ``(allowed, retry_after_seconds)``. ``rate`` is tokens per
        second and ``capacity`` is the burst size.
        """
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (capacity, now))
            tokens = min(capacity, tokens + (now - last) * rate)
            if tokens < 1.0:
                missing = 1.0 - tokens
                retry_after = missing / rate if rate > 0 else 1.0
                self._buckets[key] = (tokens, now)
                return False, max(retry_after, 0.001)
            self._buckets[key] = (tokens - 1.0, now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


rate_limiter = TokenBucketLimiter()

# 50 orders/second, burst of 50.
ORDER_RATE = 50.0
ORDER_CAPACITY = 50.0
# 100 public reads/minute, burst of 100.
PUBLIC_RATE = 100.0 / 60.0
PUBLIC_CAPACITY = 100.0
# 30 sign-in attempts/minute (brute-force protection).
AUTH_RATE = 30.0 / 60.0
AUTH_CAPACITY = 30.0
