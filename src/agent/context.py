import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from src.memory.facade import get_history, search_relevant, get_user_information, get_recent_summaries, create_person_interest, get_session_turns, set_user_information
from src.llm.factory import chat
from src.state.internal_state import get_state, state_to_text
from src.utils.logger import get_logger

logger = get_logger("agent.context")

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
_MEMORY_CHECK_PROMPT = """Detecta si este mensaje menciona a otras personas ademas del usuario que habla.
Ignora referencias al propio usuario o a Lumi.
Responde SOLO con JSON en una linea:
{"entities_found": true/false, "entities": [{"name": "Nombre", "hint": "rol o contexto breve (ej: madre, jefe, amigo)"}]}
Si no se mencionan terceras personas, entities_found=false y entities=[]."""

async def _memory_check(message: str, sid: str) -> dict:
    """Lightweight LLM call to detect third-party entities. ~200 tokens."""
    default = {"entities_found": False, "entities": []}

    turns = get_session_turns(sid, include_summarized=True, limit=4)
    transcript = ""
    for t in turns[-2:]:
        role = "Jose" if t["role"] == "user" else "Lumi"
        transcript += f"{role}: {t['content']}\n"
    transcript += f"Jose: {message}"

    try:
        response = await chat(
            messages=[
                {"role": "system", "content": _MEMORY_CHECK_PROMPT},
                {"role": "user", "content": transcript},
            ],
            max_tokens=80,
        )
        content = response.get("content", "").strip()
        match = re.search(r'\{.*"entities_found".*\}', content, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            logger.info(f"[memory_check] entities_found={data.get('entities_found')}")
            return data
        logger.warning("[memory_check] JSON regex did not match")
    except Exception as e:
        logger.warning(f"[memory_check] failed: {e}")
    return default


async def _build_dynamic_suffix(user_id: str, message: str, metadata: dict) -> str:
    state = get_state(user_id)
    now = datetime.now(COL).strftime("%d/%m/%Y %H:%M COT")
    sid = metadata.get("session_id", "default")

    relevant_memories = await search_relevant(user_id, message)
    parts = ["[Estado interno] " + state_to_text(state)]

    summaries = get_recent_summaries(user_id, limit=5)
    if summaries:
        parts.append("[Resumenes de sesiones anteriores]\n" + "\n".join("- " + s for s in summaries))

    if relevant_memories:
        parts.append("[Memorias relevantes sobre el usuario]\n" + "\n".join("- " + m for m in relevant_memories))

    info = get_user_information(user_id)
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

    # TODO: Entity resolution for third-party persons (pending — needs _memory_check wired)
    # See plan.md for implementation details.

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
