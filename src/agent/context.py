import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from src.memory.facade import get_history, search_relevant, get_user_information, get_recent_summaries
from src.state.internal_state import get_state, state_to_text

COL = timezone(timedelta(hours=-5))
SOUL_PATH = Path(__file__).parent.parent / "personality" / "lumi_soul.md"

_cached_prefix = None


def _build_cached_prefix() -> str:
    if SOUL_PATH.exists():
        return SOUL_PATH.read_text(encoding="utf-8")

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


async def _build_dynamic_suffix(user_id: str, message: str, metadata: dict) -> str:
    state = get_state(user_id)
    relevant_memories = await search_relevant(user_id, message)
    now = datetime.now(COL).strftime("%d/%m/%Y %H:%M COT")

    parts = ["[Estado interno] " + state_to_text(state)]

    summaries = get_recent_summaries(user_id, limit=5)
    if summaries:
        parts.append("[Resumenes de sesiones anteriores]\n" + "\n".join("- " + s for s in summaries))

    if relevant_memories:
        parts.append("[Memorias relevantes]\n" + "\n".join("- " + m for m in relevant_memories))

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

    channel = metadata.get("channel", "desktop")
    session_id = metadata.get("session_id", "unknown")
    parts.append("[Contexto] Canal: " + channel + " | Sesion: " + session_id + " | Hora: " + now)

    return "\n\n".join(parts)


async def build_messages(user_id: str, message: str, metadata: dict) -> list[dict]:
    cached = get_cached_prefix()
    dynamic = await _build_dynamic_suffix(user_id, message, metadata)
    system_prompt = cached + "\n\n---\n\n" + dynamic

    history = get_history(user_id, limit=5)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    return messages
