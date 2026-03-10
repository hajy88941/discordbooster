import asyncio
import logging
import time
from typing import Dict, List, Optional
from config import MAX_PER_PROXY, PROXY_BLOCK_DURATION, PROXY_MAX_FAILS
from database import Database
logger = logging.getLogger("discordboost.proxy")
class ProxyState:
    __slots__ = ("id", "url", "semaphore", "blocked_until", "fail_count")
    def __init__(self, proxy_id: int, url: str):
        self.id: int = proxy_id
        self.url: str = url
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(MAX_PER_PROXY)
        self.blocked_until: float = 0.0
        self.fail_count: int = 0
    @property
    def is_available(self) -> bool:
        return time.time() >= self.blocked_until
class ProxyManager:
    def __init__(self, db: Database):
        self._db = db
        self._proxies: Dict[int, ProxyState] = {}
        self._lock = asyncio.Lock()
        self._rr_index: int = 0
    async def load(self):
        rows = await self._db.get_all_proxies_for_load()
        async with self._lock:
            for row in rows:
                pid = row["id"]
                if pid not in self._proxies:
                    state = ProxyState(pid, row["url"])
                    state.blocked_until = row.get("blocked_until") or 0.0
                    state.fail_count = row.get("fail_count") or 0
                    self._proxies[pid] = state
        logger.info("Proxy pool initialized: %d proxies loaded, MAX_PER_PROXY=%d", len(self._proxies), MAX_PER_PROXY)
    async def get_proxy(self, proxy_id: Optional[int] = None) -> Optional[ProxyState]:
        async with self._lock:
            if proxy_id is not None and proxy_id in self._proxies:
                ps = self._proxies[proxy_id]
                if ps.is_available:
                    return ps
            available: List[ProxyState] = [p for p in self._proxies.values() if p.is_available]
            if not available:
                logger.warning("No available proxies in pool (total=%d, all blocked)", len(self._proxies))
                return None
            self._rr_index = (self._rr_index + 1) % len(available)
            return available[self._rr_index]
    async def mark_blocked(self, proxy_id: int, duration: float = PROXY_BLOCK_DURATION):
        async with self._lock:
            if proxy_id in self._proxies:
                self._proxies[proxy_id].blocked_until = time.time() + duration
        await self._db.block_proxy(proxy_id, duration)
        logger.warning("Proxy %d blocked for %.0fs due to IP-level restriction", proxy_id, duration)
    async def mark_failed(self, proxy_id: int):
        removed = False
        fail_count = 0
        async with self._lock:
            if proxy_id in self._proxies:
                self._proxies[proxy_id].fail_count += 1
                fail_count = self._proxies[proxy_id].fail_count
                if fail_count >= PROXY_MAX_FAILS:
                    del self._proxies[proxy_id]
                    removed = True
        await self._db.fail_proxy(proxy_id, PROXY_MAX_FAILS)
        if removed:
            logger.error("Proxy %d permanently deactivated: fail_count=%d reached threshold=%d", proxy_id, fail_count, PROXY_MAX_FAILS)
        else:
            logger.warning("Proxy %d network failure: fail_count=%d/%d", proxy_id, fail_count, PROXY_MAX_FAILS)
    async def mark_success(self, proxy_id: int):
        await self._db.update_proxy_used(proxy_id)
    @property
    def available_count(self) -> int:
        return sum(1 for p in self._proxies.values() if p.is_available)
    @property
    def total_count(self) -> int:
        return len(self._proxies)
