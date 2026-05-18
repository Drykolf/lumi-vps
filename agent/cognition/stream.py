"""
Core orchestrator — clasificar → handler → contexto → tools → LLM → retornar.
"""
import asyncio
import json
import os
import re

from agent.cognition import attention, intention
from agent.cognition.stimulus import handle_long_task, handle_explicit_save
from agent.expression.synapses import chat_stream, chat, ModelGroup
from agent.cognition.working_memory import build_messages
from agent.memory import save_turn, init_databases, record_turn, add_mention, get_recent_session_log
from agent.affect import init_state_table, touch_last_interaction
from agent.substrate.logger import get_logger

logger = get_logger("agent.core")

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


async def _entities_check(message: str, sid: str, user_id: str, prompt_cache_key: str | None = None) -> list[dict]:
    """Lightweight LLM call to detect third-party entities in user message. ~200 tokens."""
    default = []

    turns = get_recent_session_log(sid, include_summarized=True, limit=1)
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
            prompt_cache_key=prompt_cache_key,
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

# Inicializar bases de datos al importar
init_databases()
init_state_table()
logger.info("core orchestrator initialized")

CACHE_KEY_CHAT = os.getenv("PROMPT_CACHE_KEY_CHAT")
CACHE_KEY_TOOL = os.getenv("PROMPT_CACHE_KEY_TOOL")
CACHE_KEY_ENTITY = os.getenv("PROMPT_CACHE_KEY_ENTITY")


def _get_sid(metadata: dict) -> str:
    return metadata.get("session_id", "default")


def _finalize_turn(user_id: str, message: str, reply_text: str, sid: str, entities: list[dict] | None = None):
    history_id = save_turn(user_id, "user", message, sid)
    save_turn(user_id, "assistant", reply_text, sid)

    touch_last_interaction()

    if entities:
        for entity in entities:
            add_mention(entity, history_id=history_id, user_id=user_id, session_id=sid)

    record_turn(sid, user_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry points
# ═══════════════════════════════════════════════════════════════════════════════

async def cycle(user_id: str, message: str, metadata: dict):
    task_type = attention.classify(message)
    logger.info(f"[classify] task_type={task_type} | msg_preview={message[:80]}")
    sid = _get_sid(metadata)

    if task_type == "long_task":
        reply = await handle_long_task(user_id, message, sid)
        _finalize_turn(user_id, message, reply, sid)
        yield reply
        return

    if task_type == "explicit_save":
        reply = await handle_explicit_save(user_id, message, sid, metadata)
        _finalize_turn(user_id, message, reply, sid)
        yield reply
        return

    entities = await _entities_check(message, sid, user_id)#, prompt_cache_key=CACHE_KEY_ENTITY)

    messages = await build_messages(user_id, message, metadata, entities=entities)

    tool, args = await intention.decide_tool(sid, message)#, prompt_cache_key=CACHE_KEY_TOOL)
    if tool and args is not None:
        tool_call = [{"function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}]
        tool_results = await intention.execute(tool_call, user_id)
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}],
        })
        for r in tool_results:
            messages.append({"role": "tool", "tool_call_id": "call_1", "content": str(r.get("result", ""))})

    full_reply = ""
    async for chunk in chat_stream(messages, prompt_cache_key=CACHE_KEY_CHAT):
        full_reply += chunk
        yield chunk

    _finalize_turn(user_id, message, full_reply, sid, entities=entities)


async def run_stream(user_id: str, message: str, metadata: dict):
    async for chunk in cycle(user_id, message, metadata):
        yield chunk


async def run(user_id: str, message: str, metadata: dict) -> str:
    full = ""
    async for chunk in cycle(user_id, message, metadata):
        full += chunk
    return full
