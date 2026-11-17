"""In-process token-bucket rate limiting.

Three policies are enforced by :class:`RateLimitMiddleware`:

* authenticated order mutations: 50 requests/second per API key/bearer token
* public prediction-market reads: 100 requests/minute per client IP
* auth sign-in/registration attempts: 30 requests/minute per client IP
* collateral money mutations: 30 requests/minute per credential

For a multi-process deployment the buckets are trivially replaceable with a
Redis ``INCR``/``EXPIRE`` implementation behind the same ``allow`` interface.
"""
from __future__ import annotations

import threading
import time


MAX_BUCKETS = 20_000
BUCKET_IDLE_TTL = 600.0


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
            if len(self._buckets) >= MAX_BUCKETS and key not in self._buckets:
                stale = [k for k, (_, last_t) in self._buckets.items() if now - last_t > BUCKET_IDLE_TTL]
                for k in stale:
                    self._buckets.pop(k, None)
                if len(self._buckets) >= MAX_BUCKETS:
                    # Evict oldest quarter to bound memory under key-flooding attacks.
                    oldest = sorted(self._buckets.items(), key=lambda item: item[1][1])[: MAX_BUCKETS // 4]
                    for k, _ in oldest:
                        self._buckets.pop(k, None)
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
# 30 collateral money mutations/minute per credential (faucet abuse guard).
MONEY_RATE = 30.0 / 60.0
MONEY_CAPACITY = 30.0
