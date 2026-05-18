"""
Frequent rhythm tick — every 15 minutes.
Handles idle sessions, pending summaries, mood evaluations, and catch-up.
"""
from agent.rhythm.state import rhythm_task, rhythm_due
from agent.rhythm.cadence import MOOD_CHECK_MINUTES, MOOD_IDLE_DECAY_MINUTES
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
        #logger.info("Completed rhythm tick tasks.")


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
    Idle decay only triggers after MOOD_IDLE_DECAY_MINUTES of inactivity.
    Uses actual elapsed idle time as input to the decay formula.
    Saves updated state to core.db, marks history rows as mood_evaluated.
    Logs every mood change to traces.db mood_logs table."""
    from datetime import datetime, timezone, timedelta
    from agent.affect import get_state, idle_decay, evaluate_mood, write_state, check_emotional_honesty_mode
    from agent.memory import get_unmood_evaluated, mark_mood_evaluated, add_mood_log

    now = datetime.now(timezone.utc)
    window = timedelta(minutes=MOOD_CHECK_MINUTES * 1.5)
    since_ts = (now - window).isoformat()

    # TODO: Refactor messages by user before sending to LLM
    messages = get_unmood_evaluated(since_ts, limit=200)
    current = get_state()

    trigger = None
    note = None
    mood_change = False
    if not messages:
        last_at = current.get("last_interaction_at")
        if last_at:
            last_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            elapsed = (now - last_dt).total_seconds() / 60.0 #minutos de inactividad
        else:
            elapsed = MOOD_IDLE_DECAY_MINUTES

        if elapsed >= MOOD_IDLE_DECAY_MINUTES:
            last_updated = current.get("last_updated")
            if last_updated:
                last_up_dt = datetime.fromisoformat(last_updated)
                since_update = (now - last_up_dt).total_seconds() / 60.0
            else:
                since_update = MOOD_IDLE_DECAY_MINUTES
            if since_update >= MOOD_IDLE_DECAY_MINUTES:
                new_state = idle_decay(current, elapsed)
                trigger = "idle_decay"
                note = f"idle decay applied | idle_mins={elapsed:.0f} | since_update_mins={since_update:.0f}"
                logger.info(f"[mood_check] idle decay applied | idle_mins={elapsed:.0f}")
                mood_change = True
            else:
                new_state = current
        else:
            new_state = current
    else:
        # TODO: Add persons interest and profile of everyone involved
        new_state, reasoning = await evaluate_mood(messages, current)
        trigger = "mood_check"
        note = f"LLM eval | msgs={len(messages)} | {reasoning[:120]}"
        max_id = max(m["id"] for m in messages)
        mark_mood_evaluated(max_id)
        mood_change = True
        logger.info(f"[mood_check] LLM eval | msgs={len(messages)} | {reasoning[:120]}")

    if mood_change: 
        write_state(new_state)
        if trigger:
            add_mood_log(new_state, trigger_source=trigger, note=note)
        check_emotional_honesty_mode()


async def catch_up_pending_work() -> None:
    """Placeholder: retry failed or incomplete runs from heartbeat_runs."""
    ...
