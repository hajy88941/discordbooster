import time
from typing import List, Optional
import aiosqlite
from config import DB_PATH, MAX_RETRIES
_SCHEMA = """
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    is_active INTEGER DEFAULT 1,
    fail_count INTEGER DEFAULT 0,
    total_requests INTEGER DEFAULT 0,
    blocked_until REAL DEFAULT 0,
    last_used REAL DEFAULT 0,
    created_at REAL DEFAULT (strftime('%s', 'now'))
);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    proxy_id INTEGER,
    user_agent TEXT,
    super_properties TEXT,
    status TEXT DEFAULT 'pending',
    boost_count INTEGER DEFAULT 0,
    premium_type INTEGER DEFAULT 0,
    guilds_boosted TEXT DEFAULT '[]',
    last_check REAL,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at REAL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (proxy_id) REFERENCES proxies(id)
);
CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status, retry_count);
CREATE INDEX IF NOT EXISTS idx_accounts_last_check ON accounts(last_check);
CREATE INDEX IF NOT EXISTS idx_proxies_active ON proxies(is_active, blocked_until);
"""
class Database:
    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
    async def connect(self):
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA cache_size=-64000")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
    async def close(self):
        if self._conn:
            await self._conn.close()
    async def get_and_mark_pending(self, limit: int) -> List[dict]:
        cursor = await self._conn.execute(
            """SELECT id, token, proxy_id, user_agent, super_properties, retry_count
            FROM accounts WHERE status IN ('pending', 'error') AND retry_count < ?
            ORDER BY last_check ASC NULLS FIRST, id ASC LIMIT ?""",
            (MAX_RETRIES, limit),
        )
        rows = await cursor.fetchall()
        accounts = [dict(r) for r in rows]
        if accounts:
            ids = [a["id"] for a in accounts]
            placeholders = ",".join("?" * len(ids))
            await self._conn.execute(
                f"UPDATE accounts SET status = 'processing' WHERE id IN ({placeholders})", ids
            )
            await self._conn.commit()
        return accounts
    async def get_total_accounts(self) -> int:
        cursor = await self._conn.execute("SELECT COUNT(*) FROM accounts")
        row = await cursor.fetchone()
        return row[0]
    async def get_stats(self) -> dict:
        cursor = await self._conn.execute(
            """SELECT status, COUNT(*) AS cnt, COALESCE(SUM(boost_count), 0) AS total_boosts
            FROM accounts GROUP BY status"""
        )
        rows = await cursor.fetchall()
        return {r["status"]: {"count": r["cnt"], "total_boosts": r["total_boosts"]} for r in rows}
    async def update_account_result(
        self, account_id: int, *, status: str, boost_count: int = 0,
        premium_type: int = 0, guilds_boosted: str = "[]", error_message: Optional[str] = None
    ):
        await self._conn.execute(
            """UPDATE accounts SET status = ?, boost_count = ?, premium_type = ?,
            guilds_boosted = ?, last_check = ?, error_message = ? WHERE id = ?""",
            (status, boost_count, premium_type, guilds_boosted, time.time(), error_message, account_id),
        )
        await self._conn.commit()
    async def increment_retry(self, account_id: int, error_message: Optional[str] = None):
        await self._conn.execute(
            """UPDATE accounts SET retry_count = retry_count + 1, status = 'error',
            error_message = ?, last_check = ? WHERE id = ?""",
            (error_message, time.time(), account_id),
        )
        await self._conn.commit()
    async def requeue_account(self, account_id: int):
        await self._conn.execute("UPDATE accounts SET status = 'pending' WHERE id = ?", (account_id,))
        await self._conn.commit()
    async def assign_proxy(self, account_id: int, proxy_id: int):
        await self._conn.execute("UPDATE accounts SET proxy_id = ? WHERE id = ?", (proxy_id, account_id))
        await self._conn.commit()
    async def save_fingerprint(self, account_id: int, user_agent: str, super_properties: str):
        await self._conn.execute(
            "UPDATE accounts SET user_agent = ?, super_properties = ? WHERE id = ?",
            (user_agent, super_properties, account_id),
        )
        await self._conn.commit()
    async def reset_processing(self) -> int:
        cursor = await self._conn.execute("UPDATE accounts SET status = 'pending' WHERE status = 'processing'")
        await self._conn.commit()
        return cursor.rowcount
    async def reset_all(self) -> int:
        await self._conn.execute(
            "UPDATE accounts SET status = 'pending', retry_count = 0, last_check = NULL, error_message = NULL"
        )
        await self._conn.commit()
        return await self.get_total_accounts()
    async def get_active_proxies(self) -> List[dict]:
        now = time.time()
        cursor = await self._conn.execute(
            """SELECT id, url, fail_count, total_requests, blocked_until, last_used
            FROM proxies WHERE is_active = 1 AND blocked_until < ? ORDER BY last_used ASC""",
            (now,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    async def get_all_proxies_for_load(self) -> List[dict]:
        cursor = await self._conn.execute(
            "SELECT id, url, fail_count, blocked_until FROM proxies WHERE is_active = 1"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    async def update_proxy_used(self, proxy_id: int):
        await self._conn.execute(
            "UPDATE proxies SET total_requests = total_requests + 1, last_used = ? WHERE id = ?",
            (time.time(), proxy_id),
        )
        await self._conn.commit()
    async def block_proxy(self, proxy_id: int, duration: float):
        blocked_until = time.time() + duration
        await self._conn.execute("UPDATE proxies SET blocked_until = ? WHERE id = ?", (blocked_until, proxy_id))
        await self._conn.commit()
    async def fail_proxy(self, proxy_id: int, max_fails: int):
        await self._conn.execute("UPDATE proxies SET fail_count = fail_count + 1 WHERE id = ?", (proxy_id,))
        await self._conn.execute("UPDATE proxies SET is_active = 0 WHERE id = ? AND fail_count >= ?", (proxy_id, max_fails))
        await self._conn.commit()
    async def import_tokens(self, tokens: List[str]) -> int:
        inserted = 0
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            try:
                await self._conn.execute("INSERT OR IGNORE INTO accounts (token) VALUES (?)", (token,))
                inserted += 1
            except Exception:
                pass
        await self._conn.commit()
        return inserted
    async def import_proxies(self, proxies: List[str]) -> int:
        inserted = 0
        for proxy_url in proxies:
            proxy_url = proxy_url.strip()
            if not proxy_url:
                continue
            try:
                await self._conn.execute("INSERT OR IGNORE INTO proxies (url) VALUES (?)", (proxy_url,))
                inserted += 1
            except Exception:
                pass
        await self._conn.commit()
        return inserted
    async def export_boosted(self) -> List[dict]:
        cursor = await self._conn.execute(
            """SELECT token, boost_count, premium_type, guilds_boosted
            FROM accounts WHERE status = 'ok' AND boost_count > 0 ORDER BY boost_count DESC"""
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
