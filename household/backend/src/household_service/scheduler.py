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
        notified, skipped_goal, skipped_sub = result
        logger.info(
            "Scheduled weekly nudge sent: notified=%s skipped_already_met_goal=%s "
            "skipped_no_subscription=%s",
            notified,
            skipped_goal,
            skipped_sub,
        )


async def _balancing_tick() -> None:
    """Runs every hour on the hour; most ticks are no-ops (see
    crud.run_scheduled_balancing_if_due — it only actually runs once per
    calendar day, whichever tick gets there first)."""
    async with async_session_factory() as db:
        outcome = await crud.run_scheduled_balancing_if_due(db)
    if outcome is not None:
        logger.info(
            "Scheduled balancing run: %s task(s), %s todo(s) assigned, %s reassigned, "
            "%s task(s)/%s todo(s) left unassigned",
            len(outcome.new_task_assignments),
            len(outcome.new_todo_assignments),
            len(outcome.reassignments),
            outcome.unassigned_task_count,
            outcome.unassigned_todo_count,
        )


async def _event_group_tick() -> None:
    """Runs every hour on the hour; most ticks are no-ops — most groups
    aren't scheduled at all, and the ones that are only match one exact
    hour (see crud._event_group_due)."""
    async with async_session_factory() as db:
        triggered = await crud.run_scheduled_event_groups_if_due(db)
    for group, run, todos in triggered:
        logger.info(
            "Scheduled event group triggered: %r (run=%s, %s todo(s))",
            group.name,
            run.id,
            len(todos),
        )


async def _auto_report_tick() -> None:
    """Runs every hour on the hour; most ticks are no-ops (see
    crud.run_scheduled_auto_report_if_due — it's a "catch up" check, not
    a weekday/hour match, so it still fires correctly even after
    downtime right when a week rolled over)."""
    async with async_session_factory() as db:
        report = await crud.run_scheduled_auto_report_if_due(db)
    if report is not None:
        logger.info(
            "Scheduled weekly report generated/confirmed: id=%s %s – %s",
            report.id,
            report.period_start,
            report.period_end,
        )


async def _overdue_cleanup_tick() -> None:
    """Runs every hour on the hour; a no-op unless an admin has set
    HouseholdSettings.overdue_delete_after_days (off by default). No
    "already ran today" dedup needed — the delete query is naturally
    idempotent, a row that's already gone can't match it again on the
    next tick. Wrapped defensively (a bad row shouldn't be possible,
    but this is a real delete, not a dry run) so a failure doesn't take
    down the whole scheduler loop."""
    async with async_session_factory() as db:
        try:
            deleted = await crud.run_scheduled_overdue_cleanup(db)
        except Exception:
            await db.rollback()
            logger.exception("Scheduled overdue cleanup failed")
            return
    if deleted:
        logger.info("Scheduled overdue cleanup: deleted %s todo(s)", len(deleted))


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
    scheduler.add_job(
        _balancing_tick,
        CronTrigger(minute=5),
        id="balancing_tick",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _auto_report_tick,
        CronTrigger(minute=10),
        id="auto_report_tick",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _event_group_tick,
        CronTrigger(minute=15),
        id="event_group_tick",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _overdue_cleanup_tick,
        CronTrigger(minute=20),
        id="overdue_cleanup_tick",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("Scheduler started")


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
