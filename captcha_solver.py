import asyncio
import logging
from typing import Optional
import aiohttp
from config import CAPTCHA_API_KEY, CAPTCHA_POLL_INTERVAL, CAPTCHA_TIMEOUT
logger = logging.getLogger("discordboost.captcha")
_CREATE_TASK_URL = "https://api.2captcha.com/createTask"
_GET_RESULT_URL = "https://api.2captcha.com/getTaskResult"
class CaptchaSolver:
    def __init__(self, session: aiohttp.ClientSession):
        self._session = session
        self._api_key: str = CAPTCHA_API_KEY
        self._enabled: bool = bool(CAPTCHA_API_KEY)
        self._solved: int = 0
        self._failed: int = 0
    @property
    def is_enabled(self) -> bool:
        return self._enabled
    @property
    def stats(self) -> dict:
        return {"solved": self._solved, "failed": self._failed}
    async def solve_hcaptcha(self, sitekey: str, page_url: str = "https://discord.com") -> Optional[str]:
        if not self._enabled:
            logger.warning("Captcha solving disabled: CAPTCHA_API_KEY not configured in environment")
            return None
        try:
            task_id = await self._create_task(sitekey, page_url)
            if task_id is None:
                self._failed += 1
                return None
            solution = await self._poll_result(task_id)
            if solution:
                self._solved += 1
                logger.info("Captcha solved successfully: task_id=%s, total_solved=%d", task_id, self._solved)
            else:
                self._failed += 1
                logger.warning("Captcha solve failed: task_id=%s, total_failed=%d", task_id, self._failed)
            return solution
        except Exception as exc:
            logger.error("Captcha solver exception: type=%s, message=%s", type(exc).__name__, str(exc))
            self._failed += 1
            return None
    async def _create_task(self, sitekey: str, page_url: str) -> Optional[str]:
        payload = {
            "clientKey": self._api_key,
            "task": {"type": "HCaptchaTaskProxyless", "websiteURL": page_url, "websiteKey": sitekey},
        }
        async with self._session.post(
            _CREATE_TASK_URL, json=payload, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            data = await resp.json(content_type=None)
        if data.get("errorId", 1) != 0:
            logger.error("2captcha createTask failed: error_id=%s, description=%s",
                         data.get("errorId"), data.get("errorDescription", "unknown"))
            return None
        task_id = data.get("taskId")
        logger.debug("Captcha task created: task_id=%s, sitekey=%s", task_id, sitekey[:20])
        return str(task_id) if task_id is not None else None
    async def _poll_result(self, task_id: str) -> Optional[str]:
        elapsed = 0
        while elapsed < CAPTCHA_TIMEOUT:
            await asyncio.sleep(CAPTCHA_POLL_INTERVAL)
            elapsed += CAPTCHA_POLL_INTERVAL
            payload = {"clientKey": self._api_key, "taskId": task_id}
            try:
                async with self._session.post(
                    _GET_RESULT_URL, json=payload, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    result = await resp.json(content_type=None)
            except Exception as exc:
                logger.debug("Captcha poll network error: task_id=%s, error=%s", task_id, str(exc))
                continue
            if result.get("errorId", 1) != 0:
                logger.error("2captcha getTaskResult failed: task_id=%s, error_id=%s, description=%s",
                             task_id, result.get("errorId"), result.get("errorDescription", "unknown"))
                return None
            if result.get("status") == "ready":
                solution = result.get("solution", {})
                return solution.get("gRecaptchaResponse") or solution.get("token")
        logger.warning("Captcha poll timeout: task_id=%s, elapsed=%ds, timeout=%ds", task_id, elapsed, CAPTCHA_TIMEOUT)
        return None
