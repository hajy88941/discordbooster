import argparse
import asyncio
import sys
from logger_setup import setup_logging
logger = setup_logging()
async def cmd_run():
    from database import Database
    from dispatcher import Dispatcher
    from proxy_manager import ProxyManager
    from rate_limiter import RateLimiter
    db = Database()
    await db.connect()
    recovered = await db.reset_processing()
    if recovered:
        logger.info("Crash recovery: reset %d accounts from 'processing' to 'pending'", recovered)
    proxy_mgr = ProxyManager(db)
    await proxy_mgr.load()
    if proxy_mgr.total_count == 0:
        logger.error("No proxies in database. Import with: python main.py import-proxies <file>")
        await db.close()
        return
    total = await db.get_total_accounts()
    if total == 0:
        logger.error("No accounts in database. Import with: python main.py import-tokens <file>")
        await db.close()
        return
    rate_limiter = RateLimiter()
    dispatcher = Dispatcher(db, proxy_mgr, rate_limiter)
    try:
        await dispatcher.start()
    except asyncio.CancelledError:
        logger.info("Operation cancelled. Progress saved. Resume with: python main.py run")
    finally:
        await db.close()
async def cmd_import_tokens(filepath: str):
    from database import Database
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            tokens = [line.strip() for line in fh if line.strip()]
    except FileNotFoundError:
        logger.error("Import failed: file not found at path '%s'", filepath)
        return
    except PermissionError:
        logger.error("Import failed: permission denied for file '%s'", filepath)
        return
    if not tokens:
        logger.warning("Import skipped: file '%s' is empty or contains no valid tokens", filepath)
        return
    db = Database()
    await db.connect()
    count = await db.import_tokens(tokens)
    await db.close()
    logger.info("Token import complete: %d tokens processed from '%s'", count, filepath)
async def cmd_import_proxies(filepath: str):
    from database import Database
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            proxies = [line.strip() for line in fh if line.strip()]
    except FileNotFoundError:
        logger.error("Import failed: file not found at path '%s'", filepath)
        return
    except PermissionError:
        logger.error("Import failed: permission denied for file '%s'", filepath)
        return
    if not proxies:
        logger.warning("Import skipped: file '%s' is empty or contains no valid proxies", filepath)
        return
    db = Database()
    await db.connect()
    count = await db.import_proxies(proxies)
    await db.close()
    logger.info("Proxy import complete: %d proxies processed from '%s'", count, filepath)
async def cmd_stats():
    from database import Database
    db = Database()
    await db.connect()
    total = await db.get_total_accounts()
    stats = await db.get_stats()
    await db.close()
    logger.info("Database statistics: total_accounts=%d", total)
    if not stats:
        logger.info("  (no processed accounts yet)")
        return
    for status, info in stats.items():
        logger.info("  %-18s %6d accounts   %6d boosts", status, info["count"], info["total_boosts"])
    total_boosts = sum(i["total_boosts"] for i in stats.values())
    logger.info("  TOTAL BOOSTS: %d", total_boosts)
async def cmd_export(filepath: str):
    from database import Database
    db = Database()
    await db.connect()
    rows = await db.export_boosted()
    await db.close()
    if not rows:
        logger.info("Export skipped: no accounts with active boosts found")
        return
    try:
        with open(filepath, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(f"{row['token']}|{row['boost_count']}|{row['premium_type']}|{row['guilds_boosted']}\n")
        logger.info("Export complete: %d boosted accounts written to '%s'", len(rows), filepath)
    except PermissionError:
        logger.error("Export failed: permission denied for file '%s'", filepath)
async def cmd_reset():
    from database import Database
    db = Database()
    await db.connect()
    total = await db.reset_all()
    await db.close()
    logger.info("Reset complete: %d accounts set to 'pending' status", total)
def main():
    parser = argparse.ArgumentParser(description="Discord Boost Checker")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Start checking accounts")
    sub.add_parser("stats", help="Show current statistics")
    p_it = sub.add_parser("import-tokens", help="Import tokens from file")
    p_it.add_argument("file", help="Path to tokens file (one per line)")
    p_ip = sub.add_parser("import-proxies", help="Import proxies from file")
    p_ip.add_argument("file", help="Path to proxies file (protocol://user:pass@host:port)")
    p_ex = sub.add_parser("export", help="Export boosted accounts")
    p_ex.add_argument("file", help="Output file path")
    sub.add_parser("reset", help="Reset all accounts to pending")
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    commands = {
        "run": lambda: cmd_run(),
        "import-tokens": lambda: cmd_import_tokens(args.file),
        "import-proxies": lambda: cmd_import_proxies(args.file),
        "stats": lambda: cmd_stats(),
        "export": lambda: cmd_export(args.file),
        "reset": lambda: cmd_reset(),
    }
    coro = commands[args.command]()
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Progress saved. Resume with: python main.py run")
if __name__ == "__main__":
    main()
