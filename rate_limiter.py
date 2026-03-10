import asyncio
import logging
import time
from typing import Dict
logger = logging.getLogger("discordboost.ratelimit")
class _Bucket:
    __slots__ = ("limit", "remaining", "reset_at", "lock")
    def __init__(self):
        self.limit: int = 50
        self.remaining: int = 50
        self.reset_at: float = 0.0
        self.lock: asyncio.Lock = asyncio.Lock()
class RateLimiter:
    def __init__(self):
        self._buckets: Dict[str, _Bucket] = {}
        self._global_reset_at: float = 0.0
        self._global_lock: asyncio.Lock = asyncio.Lock()
    @staticmethod
    def _key(token: str, endpoint: str) -> str:
        return f"{token[:12]}:{endpoint}"
    def _get_bucket(self, key: str) -> _Bucket:
        if key not in self._buckets:
            self._buckets[key] = _Bucket()
        return self._buckets[key]
    async def wait_if_needed(self, token: str, endpoint: str):
        now = time.time()
        if self._global_reset_at > now:
            wait = self._global_reset_at - now
            logger.debug("Global rate-limit active, waiting %.2fs before request", wait)
            await asyncio.sleep(wait)
        key = self._key(token, endpoint)
        bucket = self._get_bucket(key)
        async with bucket.lock:
            now = time.time()
            if now >= bucket.reset_at:
                bucket.remaining = bucket.limit
            elif bucket.remaining <= 0:
                wait = bucket.reset_at - now
                if wait > 0:
                    logger.debug("Bucket %s exhausted (remaining=0), waiting %.2fs", key[:20], wait)
                    await asyncio.sleep(wait)
                bucket.remaining = bucket.limit
            bucket.remaining -= 1
    def update_from_headers(self, token: str, endpoint: str, headers: dict):
        key = self._key(token, endpoint)
        bucket = self._get_bucket(key)
        raw_limit = headers.get("X-RateLimit-Limit")
        if raw_limit is not None:
            try:
                bucket.limit = int(raw_limit)
            except (ValueError, TypeError):
                pass
        raw_remaining = headers.get("X-RateLimit-Remaining")
        if raw_remaining is not None:
            try:
                bucket.remaining = int(raw_remaining)
            except (ValueError, TypeError):
                pass
        raw_reset = headers.get("X-RateLimit-Reset")
        if raw_reset is not None:
            try:
                bucket.reset_at = float(raw_reset)
            except (ValueError, TypeError):
                pass
    async def handle_429(self, token: str, endpoint: str, headers: dict, is_global: bool = False):
        retry_after = 5.0
        raw = headers.get("Retry-After")
        if raw is not None:
            try:
                retry_after = float(raw)
            except (ValueError, TypeError):
                pass
        if is_global:
            async with self._global_lock:
                self._global_reset_at = time.time() + retry_after
            logger.warning("GLOBAL 429 received: blocking ALL tokens for %.2fs (Discord-wide rate limit)", retry_after)
        else:
            key = self._key(token, endpoint)
            bucket = self._get_bucket(key)
            bucket.remaining = 0
            bucket.reset_at = time.time() + retry_after
            logger.warning("429 rate-limited on %s: retry_after=%.2fs", key[:20], retry_after)
        await asyncio.sleep(retry_after)
    def cleanup_expired(self):
        now = time.time()
        stale = [k for k, v in self._buckets.items() if v.reset_at < now - 120]
        for k in stale:
            del self._buckets[k]
