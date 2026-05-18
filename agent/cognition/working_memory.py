import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from agent.memory import get_recent_session_log, get_recent_user_log, search_relevant, get_user_information, read_recent_diary_entries, create_person_interest, set_user_information
from agent.affect import get_state, state_to_text
from agent.substrate.logger import get_logger

logger = get_logger("agent.context")

UTC = timezone.utc
SOUL_PATH = Path(__file__).parent.parent / "identity" / "lumi_soul.md"
ATTITUDE_PATH = Path(__file__).parent.parent / "identity" / "attitude.md"

_cached_prefix = None

def _build_cached_prefix() -> str:
    parts = []

    if SOUL_PATH.exists():
        parts.append(SOUL_PATH.read_text(encoding="utf-8"))

    if ATTITUDE_PATH.exists():
        parts.append(ATTITUDE_PATH.read_text(encoding="utf-8"))

    if parts:
        return "\n\n---\n\n".join(parts)

    return (
        "Eres Lumi, asistente personal de Jose Barco. "
        "Responde en espanol colombiano neutro. "
        "Emotion tag obligatorio al inicio: [neutral], [happy], [sad], [thinking], [surprised], [playful]."
    )


def get_cached_prefix() -> str:
    global _cached_prefix
    if _cached_prefix is None:
        _cached_prefix = _build_cached_prefix()
    return _cached_prefix

async def _build_diary_suffix(user_id: str) -> str | None:
    diary = await read_recent_diary_entries(user_id=user_id, limit=7)
    if not diary:
        return None
    lines = []
    for entry in reversed(diary):
        label = entry.get("topic_label") or "sin_etiqueta"
        talked = entry.get("talked_at_ts")
        ts_str = talked.strftime("%d/%m/%Y %H:%M UTC") if talked else "?"
        users = ", ".join(entry.get("user_ids", []))
        header = f"[Diary entry — {ts_str} — topic: {label} — with: {users}]"
        lines.append(f"{header}\n{entry['summary']}")
    return "[Entradas recientes del diario de Lumi]\n" + "\n\n".join(lines)


async def _build_dynamic_suffix(user_id: str, message: str, metadata: dict) -> str:
    state = get_state()
    now = datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")
    sid = metadata.get("session_id", "default")

    relevant_memories = await search_relevant(user_id, message)
    parts = ["[Estado interno] " + state_to_text(state)]

    diary_block = await _build_diary_suffix(user_id)
    if diary_block:
        parts.append(diary_block)

    if relevant_memories:
        parts.append("[Memorias relevantes sobre el usuario]\n" + "\n".join("- " + m for m in relevant_memories))

    """info = get_user_information(user_id)
    if info["interest"] is None:
        create_person_interest(user_id)
        set_user_information(user_id, profile={})
        info = get_user_information(user_id)

    if info["profile"]:
        parts.append(f"[Usuario] {user_id}\n{json.dumps(info['profile'], ensure_ascii=False, indent=2)}")
    else:
        parts.append(f"[Usuario] {user_id}")

    if info["interest"]:
        pi = info["interest"]
        parts.append(
            f"[Interes] score={pi['interest_score']:.2f} | "
            f"tone={pi['emotional_tone']} | "
            f"status={pi['status']} | "
            f"mentions={pi['mention_count']}"
        )
"""
    # TODO: Entity resolution for third-party persons (pending — needs _entities_check wired)
    # See plan.md for implementation details.

    channel = metadata.get("channel", "desktop")
    session_id = metadata.get("session_id", "unknown")
    parts.append("[Contexto] Canal: " + channel + " | Sesion: " + session_id + " | Hora: " + now)
    parts.append("[Ubicacion] La ubicacion principal de Lumi es en Colombia, guarda todo en formato UTC, pero debe interpretar horarios a hora colombiana (UTC-5).")

    return "\n\n".join(parts)


def transcript(session_turns: list[dict], cross_turns: list[dict] | None = None, speaker_map: dict | None = None) -> list[dict]:
    """Normalize turns from session and cross-session queries into message-format dicts.
    Merges both lists, sorts by ts, strips extra fields. Stub for now."""
    all_turns = list(session_turns)
    if cross_turns:
        all_turns.extend(cross_turns)
    all_turns.sort(key=lambda t: t.get("ts", ""))
    return [{"role": t["role"], "content": t["content"]} for t in all_turns]


async def build_messages(user_id: str, message: str, metadata: dict, entities: list[dict] | None = None) -> list[dict]:
    cached = get_cached_prefix()
    dynamic = await _build_dynamic_suffix(user_id, message, metadata)
    system_prompt = cached + "\n\n---\n\n" + dynamic

    sid = metadata.get("session_id", "default")
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()

    session_turns = get_recent_session_log(sid, since_ts=since)#, limit=15)
    cross_turns = get_recent_user_log(user_id, since_ts=since, exclude_session_id=sid)#, limit=5)

    history = transcript(session_turns, cross_turns)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    return messages
