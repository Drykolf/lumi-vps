"""Lumi scheduler — periodic and cron-based tasks via APScheduler."""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from agent.substrate.logger import get_logger
from agent.rhythm.cadence import (
    COL,
    RHYTHM_TICK_MINUTES,
    DAILY_MORNING_HOUR,
    DAILY_MORNING_MINUTE,
    NIGHTLY_QUIESCENCE_HOUR,
    NIGHTLY_QUIESCENCE_MINUTE,
    WEEKLY_FORGETTING_DAY,
    WEEKLY_FORGETTING_HOUR,
    WEEKLY_FORGETTING_MINUTE,
)

logger = get_logger("rhythm.heartbeat")

logging.getLogger("apscheduler").setLevel(logging.WARNING)

scheduler = AsyncIOScheduler(timezone=COL)


def register_rhythm_jobs() -> None:
    """Register all scheduled jobs with APScheduler. Called at startup."""
    from agent.rhythm.routines.pulse import rhythm_tick
    from agent.rhythm.routines.morning import daily_morning
    from agent.rhythm.routines.quiescence import nightly_quiescence
    from agent.rhythm.routines.forgetting import weekly_forgetting

    scheduler.add_job(
        rhythm_tick,
        "interval",
        minutes=RHYTHM_TICK_MINUTES,
        timezone=COL,
        id="rhythm_tick",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        daily_morning,
        "cron",
        hour=DAILY_MORNING_HOUR,
        minute=DAILY_MORNING_MINUTE,
        timezone=COL,
        id="daily_morning",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        nightly_quiescence,
        "cron",
        hour=NIGHTLY_QUIESCENCE_HOUR,
        minute=NIGHTLY_QUIESCENCE_MINUTE,
        timezone=COL,
        id="daily_maintenance",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        weekly_forgetting,
        "cron",
        day_of_week=WEEKLY_FORGETTING_DAY,
        hour=WEEKLY_FORGETTING_HOUR,
        minute=WEEKLY_FORGETTING_MINUTE,
        timezone=COL,
        id="weekly_decay",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )


def start():
    register_rhythm_jobs()
    scheduler.start()
    logger.info("rhythm started | tz=UTC-5")
