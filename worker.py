import asyncio
import json
import logging
import random
from typing import Dict, Optional, Tuple
import aiohttp
from config import DISCORD_API_BASE, MAX_DELAY, MIN_DELAY, PROXY_BLOCK_DURATION, REQUEST_TIMEOUT
from captcha_solver import CaptchaSolver
from database import Database
from fingerprint import build_headers, generate_fingerprint
from proxy_manager import ProxyManager, ProxyState
from rate_limiter import RateLimiter
logger = logging.getLogger("discordboost.worker")
EP_ME = "/users/@me"
EP_BOOST_SUBS = "/users/@me/guilds/premium/subscriptions"
async def _request(
    session: aiohttp.ClientSession, url: str, headers: Dict[str, str],
    proxy_url: str, timeout: float = REQUEST_TIMEOUT
) -> Tuple[Optional[int], dict, Optional[dict]]:
    try:
        async with session.get(
            url, headers=headers, proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=timeout), ssl=False
        ) as resp:
            body = None
            try:
                body = await resp.json(content_type=None)
            except Exception:
                pass
            return resp.status, dict(resp.headers), body
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
        return None, {}, {"_network_error": str(exc), "_error_type": type(exc).__name__}
async def process_account(
    account: dict, session: aiohttp.ClientSession, db: Database,
    proxy_mgr: ProxyManager, rate_limiter: RateLimiter, captcha_solver: CaptchaSolver
) -> None:
    account_id: int = account["id"]
    token: str = account["token"]
    proxy: Optional[ProxyState] = await proxy_mgr.get_proxy(account.get("proxy_id"))
    if proxy is None:
        logger.debug("Account %d: no proxy available, requeuing", account_id)
        await db.requeue_account(account_id)
        return
    if account.get("proxy_id") is None or account.get("proxy_id") != proxy.id:
        await db.assign_proxy(account_id, proxy.id)
    user_agent: Optional[str] = account.get("user_agent")
    super_props: Optional[str] = account.get("super_properties")
    if not user_agent or not super_props:
        user_agent, super_props = generate_fingerprint()
        await db.save_fingerprint(account_id, user_agent, super_props)
    headers = build_headers(token, user_agent, super_props)
    status, resp_hdrs, body = await _do_request_with_semaphore(
        session, proxy, rate_limiter, token, EP_ME, headers
    )
    if status is None:
        err_type = body.get("_error_type", "Unknown")
        err_msg = body.get("_network_error", "network_error")
        logger.warning("Account %d: network error on /users/@me: type=%s, error=%s, proxy=%d",
                       account_id, err_type, err_msg[:100], proxy.id)
        await proxy_mgr.mark_failed(proxy.id)
        await db.increment_retry(account_id, f"network_error:{err_type}:{err_msg[:150]}")
        return
    rate_limiter.update_from_headers(token, EP_ME, resp_hdrs)
    await proxy_mgr.mark_success(proxy.id)
    if status == 401:
        logger.debug("Account %d: token invalid (401 Unauthorized)", account_id)
        await db.update_account_result(account_id, status="invalid_token")
        return
    if status == 429:
        is_global = bool(body and body.get("global"))
        logger.warning("Account %d: rate limited (429), global=%s", account_id, is_global)
        await rate_limiter.handle_429(token, EP_ME, resp_hdrs, is_global)
        await db.increment_retry(account_id, f"rate_limited_429:global={is_global}")
        return
    if status == 403:
        status, body = await _handle_403(
            session, proxy, rate_limiter, captcha_solver, token, EP_ME, headers,
            body, user_agent, super_props, account_id, db, proxy_mgr
        )
        if status != 200:
            return
    if status != 200:
        logger.warning("Account %d: unexpected status %d on /users/@me", account_id, status)
        await db.increment_retry(account_id, f"unexpected_status:{status}")
        return
    premium_type: int = (body or {}).get("premium_type", 0) or 0
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    status2, resp_hdrs2, body2 = await _do_request_with_semaphore(
        session, proxy, rate_limiter, token, EP_BOOST_SUBS, headers
    )
    if status2 is None:
        logger.warning("Account %d: network error on boost check, saving partial result", account_id)
        await db.update_account_result(
            account_id, status="ok", premium_type=premium_type,
            error_message="network_error_on_boost_check"
        )
        return
    rate_limiter.update_from_headers(token, EP_BOOST_SUBS, resp_hdrs2)
    if status2 == 429:
        is_global2 = bool(body2 and body2.get("global"))
        await rate_limiter.handle_429(token, EP_BOOST_SUBS, resp_hdrs2, is_global2)
        await db.update_account_result(
            account_id, status="ok", premium_type=premium_type,
            error_message="rate_limited_on_boost_check"
        )
        return
    boost_count = 0
    guilds_boosted: list = []
    if status2 == 200 and isinstance(body2, list):
        for sub in body2:
            if not sub.get("ended", False):
                boost_count += 1
                guilds_boosted.append({"subscription_id": sub.get("id"), "guild_id": sub.get("guild_id")})
    await db.update_account_result(
        account_id, status="ok", boost_count=boost_count, premium_type=premium_type,
        guilds_boosted=json.dumps(guilds_boosted, separators=(",", ":"))
    )
    if boost_count > 0:
        logger.info("Account %d: OK, premium_type=%d, active_boosts=%d", account_id, premium_type, boost_count)
async def _do_request_with_semaphore(
    session: aiohttp.ClientSession, proxy: ProxyState, rate_limiter: RateLimiter,
    token: str, endpoint: str, headers: Dict[str, str]
) -> Tuple[Optional[int], dict, Optional[dict]]:
    async with proxy.semaphore:
        await rate_limiter.wait_if_needed(token, endpoint)
        return await _request(session, f"{DISCORD_API_BASE}{endpoint}", headers, proxy.url)
async def _handle_403(
    session: aiohttp.ClientSession, proxy: ProxyState, rate_limiter: RateLimiter,
    captcha_solver: CaptchaSolver, token: str, endpoint: str, headers: Dict[str, str],
    body: Optional[dict], user_agent: str, super_props: str, account_id: int,
    db: Database, proxy_mgr: ProxyManager
) -> Tuple[int, Optional[dict]]:
    has_captcha = body and ("captcha_key" in body or "captcha_sitekey" in body)
    if has_captcha:
        sitekey = (body or {}).get("captcha_sitekey", "")
        if sitekey and captcha_solver.is_enabled:
            logger.info("Account %d: captcha required, solving via 2captcha", account_id)
            solution = await captcha_solver.solve_hcaptcha(sitekey)
            if solution:
                retry_headers = build_headers(token, user_agent, super_props, captcha_key=solution)
                s, rh, b = await _do_request_with_semaphore(
                    session, proxy, rate_limiter, token, endpoint, retry_headers
                )
                if s == 200:
                    rate_limiter.update_from_headers(token, endpoint, rh)
                    logger.info("Account %d: captcha solved, request succeeded", account_id)
                    return s, b
                logger.warning("Account %d: captcha solved but still blocked (status=%s), marking banned", account_id, s)
                await db.update_account_result(
                    account_id, status="banned", error_message=f"captcha_solved_but_blocked:status={s}"
                )
                return 0, None
            logger.warning("Account %d: captcha solve failed", account_id)
            await db.update_account_result(account_id, status="captcha_failed", error_message="captcha_solve_failed")
            return 0, None
        logger.warning("Account %d: captcha required but no sitekey or solver disabled", account_id)
        await db.update_account_result(
            account_id, status="captcha_failed",
            error_message=f"captcha_required:sitekey_present={bool(sitekey)},solver_enabled={captcha_solver.is_enabled}"
        )
        return 0, None
    logger.warning("Account %d: 403 without captcha, IP-level ban detected, blocking proxy %d", account_id, proxy.id)
    await proxy_mgr.mark_blocked(proxy.id, PROXY_BLOCK_DURATION)
    await db.update_account_result(account_id, status="banned", error_message="403_no_captcha:ip_level_block")
    return 0, None
