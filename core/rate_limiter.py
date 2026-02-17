"""
Token-bucket rate limiter for exchange API calls.

Kraken enforces ~15 requests/second for private endpoints and
~1 request/second for matching engine calls. This module provides
a thread-safe limiter that blocks until a token is available,
preventing 429 errors.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token-bucket rate limiter.

    Usage::

        limiter = RateLimiter(max_requests=900, window_seconds=60)

        # Before every API call:
        limiter.acquire(weight=1)
        response = exchange.some_api_call()

    The limiter tracks timestamps and blocks (sleeps) if the bucket
    is exhausted within the current window.
    """

    def __init__(
        self,
        max_requests: int = 900,
        window_seconds: float = 60.0,
        safety_margin: float = 0.90,
    ):
        """
        Args:
            max_requests: Total request budget per window.
            window_seconds: Sliding window size in seconds.
            safety_margin: Use only this fraction of max_requests (default 90%)
                           to leave headroom for unexpected bursts.
        """
        self.max_requests = int(max_requests * safety_margin)
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def acquire(self, weight: int = 1) -> float:
        """
        Acquire ``weight`` tokens from the bucket. Blocks if exhausted.

        Args:
            weight: Number of tokens this request costs (default 1).
                    Use higher weights for heavier endpoints (e.g., OHLCV = 5).

        Returns:
            Time spent waiting (seconds). 0.0 if no wait was needed.
        """
        wait_total = 0.0

        for _ in range(weight):
            with self._lock:
                now = time.monotonic()
                # Purge timestamps outside the window
                cutoff = now - self.window_seconds
                self._timestamps = [t for t in self._timestamps if t > cutoff]

                if len(self._timestamps) >= self.max_requests:
                    # Need to wait until the oldest timestamp expires
                    oldest = self._timestamps[0]
                    sleep_time = (oldest + self.window_seconds) - now + 0.01
                    if sleep_time > 0:
                        logger.debug(
                            "Rate limit: sleeping %.2fs (%d/%d used)",
                            sleep_time,
                            len(self._timestamps),
                            self.max_requests,
                        )
                        wait_total += sleep_time
                        time.sleep(sleep_time)
                        # Re-purge after sleep
                        now = time.monotonic()
                        cutoff = now - self.window_seconds
                        self._timestamps = [
                            t for t in self._timestamps if t > cutoff
                        ]

                self._timestamps.append(time.monotonic())

        return wait_total

    @property
    def available(self) -> int:
        """Number of tokens currently available."""
        with self._lock:
            cutoff = time.monotonic() - self.window_seconds
            active = sum(1 for t in self._timestamps if t > cutoff)
            return max(0, self.max_requests - active)

    @property
    def usage_pct(self) -> float:
        """Current usage as a percentage of capacity."""
        with self._lock:
            cutoff = time.monotonic() - self.window_seconds
            active = sum(1 for t in self._timestamps if t > cutoff)
            return active / self.max_requests if self.max_requests > 0 else 0.0

    def get_status(self) -> dict:
        """Get rate limiter status."""
        return {
            "available": self.available,
            "max_requests": self.max_requests,
            "usage_pct": f"{self.usage_pct:.1%}",
            "window_seconds": self.window_seconds,
        }
