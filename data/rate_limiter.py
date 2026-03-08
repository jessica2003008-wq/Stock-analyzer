"""Global rate limiter — token bucket with per-source limits."""
from __future__ import annotations
import logging
import threading
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class TokenBucket:
    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def acquire(self, timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                self._refill()
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
            with self.lock:
                wait = max(0, (1 - self.tokens) / self.rate)
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 0.5))

    @property
    def available(self) -> float:
        with self.lock:
            self._refill()
            return self.tokens


class RateLimiter:
    _instance = None
    _lock = threading.Lock()
    DEFAULT_LIMITS = {
        "yfinance": (0.5, 3),
        "fmp": (5.0, 10),
        "fmp_free": (0.3, 2),
        "eastmoney": (2.0, 5),
        "edgar": (10.0, 10),
        "default": (2.0, 5),
    }

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._buckets = {}
                    cls._instance._bucket_lock = threading.Lock()
                    cls._instance._stats = defaultdict(lambda: {"total": 0, "throttled": 0})
        return cls._instance

    def get_bucket(self, source: str) -> TokenBucket:
        with self._bucket_lock:
            if source not in self._buckets:
                rate, burst = self.DEFAULT_LIMITS.get(source, self.DEFAULT_LIMITS["default"])
                self._buckets[source] = TokenBucket(rate, burst)
            return self._buckets[source]

    def acquire(self, source: str, timeout: float = 120.0) -> bool:
        bucket = self.get_bucket(source)
        self._stats[source]["total"] += 1
        acquired = bucket.acquire(timeout)
        if not acquired:
            self._stats[source]["throttled"] += 1
        return acquired


_limiter = None

def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
