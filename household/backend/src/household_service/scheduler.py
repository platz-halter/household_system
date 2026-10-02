"""Background job scheduling (APScheduler) for this service.

This is the general-purpose piece any future time-based feature should
register a job with — the weekly reminder below is the first tenant, not
the only one this is built for.

Design notes:
- `AsyncIOScheduler` attaches to the event loop it's started from, so
  `start()`/`shutdown()` must be called from FastAPI's async lifespan
  (see main.py), not at import time.
- The jobstore is in-memory: job *definitions* (which functions run on
  what cron schedule) are re-registered from code on every startup, so
  they don't need to survive a restart by themselves. Anything that must
  not double-fire across restarts (like "did this week's nudge already
  go out") is persisted in the database by the job itself, not by
  APScheduler — see crud.run_scheduled_nudge_if_due.
- Jobs open their own DB session via `async_session_factory` since they
  run outside any request (no `Depends(get_db)` available).
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from shared.db import async_session_factory

from household_service import crud

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


async def _weekly_nudge_tick() -> None:
    """Runs every hour on the hour; most ticks are no-ops (see
    crud.run_scheduled_nudge_if_due for the actual eligibility check)."""
    async with async_session_factory() as db:
        result = await crud.run_scheduled_nudge_if_due(db)
    if result is not None:
        notified, skipped = result
        logger.info(
            "Scheduled weekly nudge sent: notified=%s skipped=%s", notified, skipped
        )


def start() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        _weekly_nudge_tick,
        CronTrigger(minute=0),
        id="weekly_nudge_tick",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("Scheduler started")


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
