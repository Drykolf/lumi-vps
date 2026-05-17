import json
import re
from pathlib import Path
from datetime import datetime, timezone
from agent.memory import add_mention,get_history, search_relevant, get_user_information, get_recent_summaries, create_person_interest, get_recent_session_history, set_user_information
from agent.expression.synapses import chat, ModelGroup
from agent.affect import get_state, state_to_text
from agent.substrate.logger import get_logger

logger = get_logger("agent.context")

UTC = timezone.utc
SOUL_PATH = Path(__file__).parent.parent / "identity" / "lumi_soul.md"
ATTITUDE_PATH = Path(__file__).parent.parent / "identity" / "attitude.md"

_ENTITY_CHECK_PROMPT = """Extrae todas las menciones explícitas de personas humanas y referencias relacionales posesivas a personas humanas en el mensaje del usuario.

Reglas:
- Devuelve una lista JSON.
- Incluye nombres propios, apodos y nombres compuestos.
- Incluye referencias sin nombre cuando indiquen una persona por relación con el usuario: "mi mamá", "mi papá", "mi jefe", "mi hermana", "mi novia", "mi amigo", "mi socio", etc.
- Incluye varias personas si aparecen en el mismo mensaje.
- No inventes nombres.
- No resuelvas quién es la persona en la base de datos.
- No asumas que dos personas con el mismo nombre son la misma persona.
- Si hay descriptor relacional, inclúyelo: "mamá", "prima", "jefe", "amiga", "de la oficina", etc.
- Si la referencia es posesiva, usa anchor="user".
- En el campo anchor, usa el user_id del hablante (el valor antes de ":" en cada linea del transcript) que menciono a la persona. Si la mencion no tiene hablante claro, usa null.
- Excluye al asistente.
- Excluye al usuario salvo que el usuario se mencione explícitamente por nombre en tercera persona.
- Si no hay personas explícitas ni referencias relacionales humanas, devuelve [].
-Excluye referencias a entidades no humanas como empresas, juegos, apps, productos, eventos, etc.
-Excluye referencias vagas como "alguien", "un amigo", "una persona", etc. salvo que tengan un descriptor claro como "un amigo de la universidad", "alguien de la oficina", etc.
-Excluye referencias a Lumi como "Lumi", "la asistente", "mi asistente", etc.
Formato:
[
  {
    "raw_text": "...",
    "mention_type": "named_person | role_reference | named_person_with_role",
    "raw_name": "... | null",
    "normalized_name": "... | null",
    "descriptor": "... | null",
    "relation_label_hint": "... | null",
    "anchor": "user_id_del_hablante | null",
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

async def _entities_check(message: str, sid: str, user_id: str) -> list[dict]:
    """Lightweight LLM call to detect third-party entities in user message. ~200 tokens."""
    default = []

    turns = get_recent_session_history(sid, include_summarized=True, limit=1)
    transcript = ""
    for t in turns:
        speaker = t["user_id"] if t["role"] == "user" else "Lumi"
        transcript += f"{speaker}: {t['content']}\n"
    transcript += f"{user_id}: {message}"

    try:
        response = await chat(
            messages=[
                {"role": "system", "content": _ENTITY_CHECK_PROMPT},
                {"role": "user", "content": transcript},
            ],
            max_tokens=500,
            temperature=0.1,
            reasoning_effort="none",
            model_group=ModelGroup.LIGHTWEIGHT,
        )
        content = response.get("content", "").strip()
        logger.info(f"[entities_check] response: {content}")
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            entities = json.loads(match.group(0))
            if not entities:
                return []
            for e in entities:
                logger.info(f"[entities_check] raw_text={e.get('raw_text', '')}")
            return entities
        logger.warning("[entities_check] JSON array regex did not match")
    except Exception as e:
        logger.warning(f"[entities_check] failed: {e}")
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
    entities =await _entities_check(message, sid, user_id)
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


async def build_messages(user_id: str, message: str, metadata: dict, entities: list[dict] | None = None) -> list[dict]:
    cached = get_cached_prefix()
    dynamic = await _build_dynamic_suffix(user_id, message, metadata)
    system_prompt = cached + "\n\n---\n\n" + dynamic

    history = get_history(user_id, limit=5)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    return messages
