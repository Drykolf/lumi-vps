"""Lumi scheduler — periodic and cron-based tasks via APScheduler."""
import logging
from datetime import timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from agent.substrate.logger import get_logger

COL = timezone(timedelta(hours=-5))
logger = get_logger("rhythm.heartbeat")

# Suppress APScheduler's own job lifecycle logs
logging.getLogger("apscheduler").setLevel(logging.WARNING)

scheduler = AsyncIOScheduler(timezone=COL)


# ── Active jobs ────────────────────────────────────────────────────────────────

#@scheduler.scheduled_job("interval", minutes=5)
async def beat():
    logger.info("beat — Lumi scheduler alive")


@scheduler.scheduled_job("interval", minutes=10)
async def idle_session_check():
    from agent.memory.session import get_stale_sessions, reset_turns
    from agent.memory.consolidation import generate_summary
    #logger.info("idle sessions check")
    stale = get_stale_sessions(inactive_minutes=30)
    if not stale:
        return

    logger.info("idle sessions found: %d", len(stale))
    for sid in stale:
        summary = await generate_summary(sid)
        reset_turns(sid)
        logger.info("  session=%s summarized=%s", sid, bool(summary))


# ── Rhythm jobs (cron) ──────────────────────────────────────────────────────────

@scheduler.scheduled_job('cron', hour=7, minute=0)
async def daily_morning():
    """Mood regression toward baseline at 7am COT (mood_policy.md)."""
    logger.info("daily_morning fired")


@scheduler.scheduled_job('cron', hour=3, minute=0)
async def daily_maintenance():
    """Memory tier checks + family inference + cleanup at 3am COT."""
    logger.info("daily_maintenance fired")


@scheduler.scheduled_job('cron', day_of_week='mon', hour=4, minute=0)
async def weekly_decay():
    """Interest score decay for inactive persons (interest_policy.md)."""
    logger.info("weekly_decay fired")


# ── Lifecycle ──────────────────────────────────────────────────────────────────

def start():
    scheduler.start()
    logger.info("rhythm started | tz=UTC-5")


"""TODO
heartbeat.py	Perfecto para beat operativo.
quiescence.py	Muy bueno para idle check / reposo / consolidación nocturna.
cadence.py	Muy bueno para intervalos, timers y configuración temporal.
"""