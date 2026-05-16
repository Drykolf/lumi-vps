import json
import re
from pathlib import Path
from datetime import datetime, timezone
from agent.memory import get_history, search_relevant, get_user_information, get_recent_summaries, create_person_interest, get_session_turns, set_user_information
from agent.expression.synapses import chat
from agent.affect import get_state, state_to_text
from agent.substrate.logger import get_logger

logger = get_logger("agent.context")

UTC = timezone.utc
SOUL_PATH = Path(__file__).parent.parent / "identity" / "lumi_soul.md"
ATTITUDE_PATH = Path(__file__).parent.parent / "identity" / "attitude.md"

_MEMORY_CHECK_PROMPT = """Extrae todas las menciones explícitas de personas humanas en el mensaje del usuario.

Reglas:
- Devuelve una lista JSON.
- Incluye nombres propios, apodos y nombres compuestos.
- Incluye varias personas si aparecen en el mismo mensaje.
- No inventes nombres.
- No resuelvas quién es la persona en la base de datos.
- No asumas que dos personas con el mismo nombre son la misma persona.
- Si hay descriptor relacional, inclúyelo: "mamá", "prima", "jefe", "amiga", "de la oficina", etc.
- Excluye al asistente.
- Excluye al usuario salvo que el usuario se mencione explícitamente por nombre en tercera persona.
- Si no hay personas explícitas, devuelve [].

Formato:
[
  {
    "raw_name": "...",
    "normalized_name": "...",
    "descriptor": "... | null",
    "confidence": 0.0-1.0
  }
]"""

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
    state = get_state()
    now = datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")
    sid = metadata.get("session_id", "default")

    relevant_memories = await search_relevant(user_id, message)
    parts = ["[Estado interno] " + state_to_text(state)]

    summaries = get_recent_summaries(user_id, limit=5)
    if summaries:
        parts.append("[Resumenes de sesiones anteriores]\n" + "\n".join("- " + s for s in summaries))

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
    # TODO: Entity resolution for third-party persons (pending — needs _memory_check wired)
    # See plan.md for implementation details.

    channel = metadata.get("channel", "desktop")
    session_id = metadata.get("session_id", "unknown")
    parts.append("[Contexto] Canal: " + channel + " | Sesion: " + session_id + " | Hora: " + now)
    parts.append("[Ubicacion] La ubicacion principal de Lumi es en Colombia, guarda todo en formato UTC, pero debe interpretar horarios a hora colombiana (UTC-5).")

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
