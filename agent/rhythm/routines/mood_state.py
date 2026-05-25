"""
Hourly mood evaluation tick.
Handles idle decay and LLM-based contextual mood evaluation.
"""
from agent.rhythm.state import rhythm_task
from agent.rhythm.cadence import MOOD_CHECK_MINUTES, MOOD_IDLE_DECAY_MINUTES
from agent.substrate.logger import get_logger
logger = get_logger("rhythm.mood_state")


async def mood_state_tick():
    """Every MOOD_CHECK_MINUTES: contextual or idle mood evaluation."""
    async with rhythm_task("mood_check"):
        await mood_check()


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
    """Idle decay or LLM contextual evaluation.
    Idle decay only triggers after MOOD_IDLE_DECAY_MINUTES of inactivity.
    Uses heartbeat_state.last_success_at as period_start bookmark."""
    from datetime import datetime, timezone, timedelta
    from agent.affect import get_state, idle_decay, evaluate_mood, write_state, check_emotional_honesty_mode
    from agent.memory import get_history_since, add_mood_log
    from agent.rhythm.state import get_last_success

    now = datetime.now(timezone.utc)
    last_success = await get_last_success("mood_check")
    if last_success:
        since_ts = last_success.isoformat()
    else:
        since_ts = (now - timedelta(minutes=MOOD_CHECK_MINUTES * 1.5)).isoformat()

    messages = get_history_since(since_ts, limit=200)
    current = get_state()

    trigger = None
    note = None
    mood_change = False
    if not messages:
        last_at = current.get("last_interaction_at")
        if last_at:
            last_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            elapsed = (now - last_dt).total_seconds() / 60.0
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
        note = f"LLM eval | msgs={len(messages)} | {reasoning[:200]}"
        mood_change = True
        logger.info(f"[mood_check] LLM eval | msgs={len(messages)} | {reasoning[:200]}")

    if mood_change:
        write_state(new_state)
        if trigger:
            add_mood_log(new_state, trigger_source=trigger, note=note)
        check_emotional_honesty_mode()
