"""
Frequent rhythm tick — every 15 minutes.
Handles idle sessions, pending summaries, mood evaluations, and catch-up.
"""
from agent.rhythm.state import rhythm_task, rhythm_due
from agent.rhythm.cadence import MOOD_CHECK_MINUTES
from agent.substrate.logger import get_logger
logger = get_logger("rhythm.pulse")

async def rhythm_tick():
    """Every RHYTHM_TICK_MINUTES: idle sessions, summaries, mood, catch-up."""
    async with rhythm_task("rhythm_tick"):
        await idle_session_check()
        await process_pending_summaries()
        await process_pending_mood_evaluations()
        await catch_up_pending_work()
        if await rhythm_due("mood_check", every_minutes=MOOD_CHECK_MINUTES):
            async with rhythm_task("mood_check"):
                await mood_check()
        logger.info("Completed rhythm tick tasks.")


async def idle_session_check() -> None:
    """Finds sessions inactive for 30+ minutes, generates summaries, resets."""
    from agent.rhythm.cadence import IDLE_SESSION_MINUTES
    from agent.memory.mindstream.session import get_stale_sessions, reset_turns
    from agent.memory.mindstream.consolidation import generate_summary

    stale = get_stale_sessions(inactive_minutes=IDLE_SESSION_MINUTES)
    if not stale:
        return

    for sid in stale:
        await generate_summary(sid)
        reset_turns(sid)


async def process_pending_summaries() -> None:
    """Placeholder: summarize closed sessions not yet summarized."""
    ...


async def process_pending_mood_evaluations() -> None:
    """Placeholder: apply session mood deltas for unevaluated sessions."""
    ...


async def mood_check() -> None:
    """Hourly mood evaluation: idle decay or LLM contextual evaluation.
    Saves updated state to core.db, marks history rows as mood_evaluated."""
    from datetime import datetime, timezone, timedelta
    from agent.affect import get_state, idle_decay, evaluate_mood, write_state, check_emotional_honesty_mode
    from agent.memory import get_unmood_evaluated, mark_mood_evaluated

    now = datetime.now(timezone.utc)
    window = timedelta(minutes=MOOD_CHECK_MINUTES * 1.5)
    since_ts = (now - window).isoformat()

    # TODO: Refactor messages by user before sending to LLM
    messages = get_unmood_evaluated(since_ts, limit=200)
    current = get_state()

    if not messages:
        new_state = idle_decay(current, MOOD_CHECK_MINUTES)
        logger.info("[mood_check] idle decay applied | no new messages in window")
    else:
        # TODO: Add persons interest and profile of everyone involved
        new_state, reasoning = await evaluate_mood(messages, current)
        #logger.info(f"[mood_check] LLM eval {new_state} | reasoning={reasoning[:120]}")
        max_id = max(m["id"] for m in messages)
        mark_mood_evaluated(max_id)
        logger.info(f"[mood_check] LLM eval | msgs={len(messages)} | {reasoning[:120]}")

    write_state(new_state)
    check_emotional_honesty_mode()


async def catch_up_pending_work() -> None:
    """Placeholder: retry failed or incomplete runs from heartbeat_runs."""
    ...
