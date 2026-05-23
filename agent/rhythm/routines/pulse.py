"""
Frequent rhythm tick — every 15 minutes.
Handles idle sessions, mood evaluations, and catch-up.
"""
from agent.rhythm.state import rhythm_task, rhythm_due
from agent.rhythm.cadence import MOOD_CHECK_MINUTES, MOOD_IDLE_DECAY_MINUTES
from agent.substrate.logger import get_logger
logger = get_logger("rhythm.pulse")

async def rhythm_tick():
    """Every RHYTHM_TICK_MINUTES: idle sessions, mood, catch-up."""
    async with rhythm_task("rhythm_tick"):
        await process_pending_mood_evaluations()
        await catch_up_pending_work()
        if await rhythm_due("mood_check", every_minutes=MOOD_CHECK_MINUTES):
            async with rhythm_task("mood_check"):
                await mood_check()
        #logger.info("Completed rhythm tick tasks.")


async def process_pending_mood_evaluations() -> None:
    """Placeholder: apply session mood deltas for unevaluated sessions."""
    ...


def _build_involved_people(messages: list[dict]) -> dict:
    """Build involved_people dict for mood eval from resolved mentions in a message window.
    Only includes persons with resolution_status='resolved' (score >= 0.96)."""
    from agent.memory import get_resolved_mentions_by_history_ids, get_known_person, get_relations

    history_ids = [m["id"] for m in messages if "id" in m]
    if not history_ids:
        return {}

    mentions = get_resolved_mentions_by_history_ids(history_ids)
    seen: set[str] = set()
    result: dict = {}

    for mention in mentions:
        pid = mention.get("resolved_person_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)

        person = get_known_person(pid)
        if not person:
            continue

        relations = get_relations(pid) or []
        result[pid] = {
            "display_name": person.get("display_name"),
            "interest_score": person.get("interest_score"),
            "emotional_tone": person.get("emotional_tone"),
            "relations": [
                {
                    "relation_type": r.get("relation_type"),
                    "target_person_id": r.get("target_person_id"),
                }
                for r in relations
            ],
        }

    return result


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
        involved_people = _build_involved_people(messages)
        new_state, reasoning = await evaluate_mood(messages, current, involved_people=involved_people or None)
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
