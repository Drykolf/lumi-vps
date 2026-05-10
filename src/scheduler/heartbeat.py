"""Lumi scheduler — periodic and cron-based tasks via APScheduler."""
import logging
from datetime import timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.utils.logger import get_logger

COL = timezone(timedelta(hours=-5))
logger = get_logger("scheduler.heartbeat")

# Suppress APScheduler's own job lifecycle logs
logging.getLogger("apscheduler").setLevel(logging.WARNING)

scheduler = AsyncIOScheduler(timezone=COL)


# ── Active jobs ────────────────────────────────────────────────────────────────

#@scheduler.scheduled_job("interval", minutes=5)
async def beat():
    logger.info("beat — Lumi scheduler alive")


@scheduler.scheduled_job("interval", minutes=10)
async def idle_session_check():
    from src.memory.session_tracker import get_stale_sessions, reset_turns
    from src.memory.summary import generate_summary
    logger.info("idle sessions check")
    stale = get_stale_sessions(inactive_minutes=30)
    if not stale:
        return

    logger.info("idle sessions found: %d", len(stale))
    for sid in stale:
        summary = await generate_summary(sid)
        reset_turns(sid)
        logger.info("  session=%s summarized=%s", sid, bool(summary))


# ── Future jobs (TODOs) ────────────────────────────────────────────────────────

# TODO: @scheduler.scheduled_job('cron', hour=7, minute=0)
# async def morning_greeting():
#     """Greet Jose after waking up. Push via bridge if connected,
#     queue as pending message otherwise."""

# TODO: @scheduler.scheduled_job('cron', day_of_week='mon', hour=0, minute=0)
# async def weekly_decay():
#     """Run interest score decay for inactive persons (interest_policy.md)."""

# TODO: @scheduler.scheduled_job('cron', hour=7, minute=0)
# async def morning_reset():
#     """Daily mood regression toward baseline (mood_policy.md)."""


# ── Lifecycle ──────────────────────────────────────────────────────────────────

def start():
    scheduler.start()
    logger.info("scheduler started | beat=5min | tz=UTC-5")
