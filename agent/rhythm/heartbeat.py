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

@scheduler.scheduled_job("interval", minutes=15)
async def rhythm_tick():
    """sesión inactiva hace 30 min
        summary pendiente
        mood_eval pendiente
        idle drift horario
        catch-up si algo quedó sin procesar"""
    """Frequent rhythm: idle sessions, pending summaries, session mood deltas, hourly mood drift."""
    logger.info("rhythm_tick fired")
    await idle_session_check()

    #if await rhythm_due("hourly_mood_check", every_minutes=60):
     #   async with rhythm_task("hourly_mood_check"):
      #      await mood_check()

# ── Rhythm jobs (cron) ──────────────────────────────────────────────────────────

@scheduler.scheduled_job('cron', hour=7, minute=0)
async def daily_morning():
    """Lumi amanece.
        Se centra.
        Baja irritación.
        Recupera energía."""
    """Mood regression toward baseline at 7am COT (mood_policy.md)."""
    logger.info("daily_morning fired")


@scheduler.scheduled_job('cron', hour=3, minute=0)
async def daily_maintenance():
    """consolidar memorias
        analizar perfiles
        relaciones
        tareas realizadas
        aprendizajes
        memoria del día"""
    """Memory tier checks + family inference + cleanup at 3am COT."""
    logger.info("daily_maintenance fired")


@scheduler.scheduled_job('cron', day_of_week='mon', hour=4, minute=0)
async def weekly_decay():
    #olvido / enfriamiento social
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