"""
Background Tasks
────────────────
Two lightweight tasks run after app startup:

  1. sync_endpoints   (every  5 min) — discover new endpoints from logs
  2. update_stats     (every 10 min) — refresh aggregate counters

AI analysis is NOT run in background — it only runs when:
  - User clicks "Re-analyze" on an endpoint
  - User clicks "Generate Documentation" in GitHub tab
  - GitHub webhook fires on a push event

This avoids burning Gemini API quota on constant background polling.
"""

import asyncio
import logging

from app.database import AsyncSessionLocal
from app.services.log_service import LogService
from app.services.endpoint_service import EndpointService, normalize_path

logger = logging.getLogger(__name__)


async def sync_endpoints():
    async with AsyncSessionLocal() as db:
        try:
            log_svc = LogService(db)
            ep_svc  = EndpointService(db)
            rows = await log_svc.get_path_stats(hours=1)
            new  = 0
            for row in rows:
                pattern  = normalize_path(row["path"])
                existing = await ep_svc.get_by_path(row["method"], pattern)
                if not existing:
                    await ep_svc.get_or_create(row["method"], row["path"])
                    new += 1
            await db.commit()
            if new:
                logger.info(f"[BG] sync_endpoints: discovered {new} new endpoint(s)")
        except Exception as exc:
            logger.error(f"[BG] sync_endpoints error: {exc}")
            await db.rollback()


async def update_stats():
    async with AsyncSessionLocal() as db:
        try:
            ep_svc    = EndpointService(db)
            endpoints = await ep_svc.list_all()
            for ep in endpoints:
                await ep_svc.update_stats(ep.id)
            await db.commit()
            logger.info(f"[BG] update_stats: refreshed {len(endpoints)} endpoints")
        except Exception as exc:
            logger.error(f"[BG] update_stats error: {exc}")
            await db.rollback()


async def _loop(fn, interval: int, name: str):
    while True:
        try:
            await fn()
        except Exception as exc:
            logger.error(f"[BG] {name} unhandled error: {exc}")
        await asyncio.sleep(interval)


async def start_background_tasks():
    logger.info("[BG] Starting background tasks…")
    await asyncio.gather(
        _loop(sync_endpoints, 300,  "sync_endpoints"),
        _loop(update_stats,   600,  "update_stats"),
        # AI analysis removed — on-demand only via GitHub tab or Re-analyze button
    )
