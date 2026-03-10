import asyncio
import logging
import time
import aiohttp
from captcha_solver import CaptchaSolver
from config import BATCH_SIZE, MAX_WORKERS, QUEUE_SIZE
from database import Database
from proxy_manager import ProxyManager
from rate_limiter import RateLimiter
from worker import process_account
logger = logging.getLogger("discordboost.dispatcher")
_MONITOR_INTERVAL = 30
_FEEDER_PAUSE = 0.2
_NO_PROXY_PAUSE = 30
class Dispatcher:
    def __init__(self, db: Database, proxy_mgr: ProxyManager, rate_limiter: RateLimiter):
        self._db = db
        self._proxy_mgr = proxy_mgr
        self._rate_limiter = rate_limiter
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._stop = asyncio.Event()
        self._processed: int = 0
        self._start_time: float = 0.0
        self._total: int = 0
    async def start(self):
        self._start_time = time.time()
        self._total = await self._db.get_total_accounts()
        logger.info("Dispatcher starting: total_accounts=%d, workers=%d, proxies=%d, queue_size=%d, batch_size=%d",
                    self._total, MAX_WORKERS, self._proxy_mgr.total_count, QUEUE_SIZE, BATCH_SIZE)
        connector = aiohttp.TCPConnector(
            limit=MAX_WORKERS * 2, limit_per_host=0, ttl_dns_cache=300, enable_cleanup_closed=True
        )
        async with aiohttp.ClientSession(connector=connector) as session:
            captcha_solver = CaptchaSolver(session)
            workers = [asyncio.create_task(self._worker(session, captcha_solver, i)) for i in range(MAX_WORKERS)]
            feeder = asyncio.create_task(self._feed_queue())
            monitor = asyncio.create_task(self._monitor())
            await feeder
            await self._queue.join()
            self._stop.set()
            for _ in range(MAX_WORKERS):
                await self._queue.put(None)
            await asyncio.gather(*workers, return_exceptions=True)
            monitor.cancel()
        await self._print_summary()
    async def _feed_queue(self):
        while not self._stop.is_set():
            if self._proxy_mgr.available_count == 0:
                logger.warning("All proxies blocked or unavailable, pausing feeder for %ds", _NO_PROXY_PAUSE)
                await asyncio.sleep(_NO_PROXY_PAUSE)
                continue
            accounts = await self._db.get_and_mark_pending(BATCH_SIZE)
            if not accounts:
                logger.info("Feeder exhausted: no more pending accounts in database")
                break
            for acc in accounts:
                if self._stop.is_set():
                    break
                await self._queue.put(acc)
            await asyncio.sleep(_FEEDER_PAUSE)
    async def _worker(self, session: aiohttp.ClientSession, captcha_solver: CaptchaSolver, worker_id: int):
        while True:
            account = await self._queue.get()
            if account is None:
                self._queue.task_done()
                break
            try:
                await process_account(account, session, self._db, self._proxy_mgr, self._rate_limiter, captcha_solver)
            except Exception as exc:
                aid = account.get("id", "?")
                logger.error("Worker %d unhandled exception: account_id=%s, error_type=%s, error=%s",
                             worker_id, aid, type(exc).__name__, str(exc)[:200])
                try:
                    await self._db.increment_retry(account["id"], f"unhandled_exception:{type(exc).__name__}:{str(exc)[:150]}")
                except Exception:
                    pass
            finally:
                self._processed += 1
                self._queue.task_done()
    async def _monitor(self):
        try:
            while not self._stop.is_set():
                await asyncio.sleep(_MONITOR_INTERVAL)
                elapsed = time.time() - self._start_time
                rate = self._processed / elapsed if elapsed > 0 else 0
                remaining = max(self._total - self._processed, 0)
                eta = remaining / rate if rate > 0 else 0
                stats = await self._db.get_stats()
                parts = [f"{s}:{info['count']}" for s, info in stats.items()]
                logger.info("Progress %d/%d (%.1f/s) | ETA %.0fs | Queue %d | Proxies %d/%d | %s",
                            self._processed, self._total, rate, eta, self._queue.qsize(),
                            self._proxy_mgr.available_count, self._proxy_mgr.total_count, " | ".join(parts))
                self._rate_limiter.cleanup_expired()
        except asyncio.CancelledError:
            pass
    async def _print_summary(self):
        elapsed = time.time() - self._start_time
        stats = await self._db.get_stats()
        logger.info("=" * 60)
        logger.info("COMPLETED: duration=%.1fs, accounts_processed=%d, rate=%.1f/s",
                    elapsed, self._processed, self._processed / elapsed if elapsed > 0 else 0)
        for status, info in stats.items():
            logger.info("  %-18s %6d accounts   %6d boosts", status, info["count"], info["total_boosts"])
        total_boosts = sum(i["total_boosts"] for i in stats.values())
        logger.info("  TOTAL BOOSTS FOUND: %d", total_boosts)
        logger.info("=" * 60)
