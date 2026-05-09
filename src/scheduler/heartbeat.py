"""Lumi scheduler — periodic and cron-based tasks via APScheduler."""
import logging
from datetime import timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

COL = timezone(timedelta(hours=-5))

logger = logging.getLogger("scheduler.heartbeat")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(asctime)s] %(message)s"))
    logger.addHandler(_h)

# Suppress APScheduler's own job lifecycle logs
logging.getLogger("apscheduler").setLevel(logging.WARNING)

scheduler = AsyncIOScheduler(timezone=COL)


# ── Active jobs ────────────────────────────────────────────────────────────────

@scheduler.scheduled_job("interval", minutes=5)
async def beat():
    logger.info("beat — Lumi scheduler alive")


# ── Future jobs (TODOs) ────────────────────────────────────────────────────────

# TODO: @scheduler.scheduled_job('cron', hour=7, minute=0)
# async def morning_greeting():
#     """Greet Jose after waking up. Push via bridge if connected,
#     queue as pending message otherwise."""

# TODO: @scheduler.scheduled_job('interval', minutes=10)
# async def idle_session_check():
#     """Check sessions with >1h inactivity → trigger summary via generate_summary()."""

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
