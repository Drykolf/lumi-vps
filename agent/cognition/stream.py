"""
Core orchestrator — clasificar → handler → contexto → tools → LLM → retornar.
"""
import asyncio
import json
import os
import re
from datetime import timezone, timedelta

from agent.cognition import attention, intention
from agent.cognition.stimulus import handle_long_task, handle_explicit_save
from agent.expression.synapses import chat_stream, chat, ModelGroup
from agent.cognition.working_memory import build_messages
from agent.memory import (
    save_turn,
    init_databases,
    add_mention,
    update_mention_resolution,
    get_recent_session_log,
    resolve_person_mention,
    get_known_person,
    get_relations,
    search_relevant,
)
from agent.affect import init_state_table, touch_last_interaction
from agent.substrate.logger import get_logger

logger = get_logger("agent.core")

_ENTITY_CHECK_PROMPT = """Extrae todas las menciones explícitas de personas humanas y referencias relacionales posesivas a personas humanas en el mensaje del usuario.

Reglas:
- Devuelve una lista JSON.
- Incluye nombres propios, apodos y nombres compuestos.
- Incluye referencias sin nombre cuando indiquen una persona por relación con el usuario: "mi mamá", "mi papá", "mi jefe", "mi hermana", "mi novia", "mi amigo", "mi socio", etc.
- Incluye varias personas si aparecen en el mismo mensaje.
- CRÍTICO: Crea una entrada separada por cada persona individual. Si se mencionan múltiples personas en una lista ("sofia, gloria, andres, y pablo"), crea un objeto distinto por cada nombre — nunca los agrupes en un solo objeto.
- No inventes nombres.
- No resuelvas quién es la persona en la base de datos.
- No asumas que dos personas con el mismo nombre son la misma persona.
- Si hay descriptor relacional, inclúyelo: "mamá", "prima", "jefe", "amiga", "de la oficina", etc.
- Si la referencia es posesiva, usa anchor="user".
- En el campo anchor, usa el user_id del hablante (el valor antes de ":" en cada linea del transcript) que menciono a la persona. Si la mencion no tiene hablante claro, usa null.
- Los prefijos de formato "user_id:" al inicio de cada línea del transcript son etiquetas del hablante, no menciones de personas. No los extraigas como menciones.
- Excluye al asistente.
- Excluye a los hablantes del transcript (cualquier user_id que aparezca como prefijo de línea) salvo que ese mismo nombre aparezca DENTRO del contenido de un mensaje refiriéndose a esa persona en tercera persona.
- Si no hay personas explícitas ni referencias relacionales humanas, devuelve [].
-Excluye referencias a entidades no humanas como empresas, juegos, apps, productos, eventos, etc.
-Excluye referencias vagas como "alguien", "un amigo", "una persona", etc. salvo que tengan un descriptor claro como "un amigo de la universidad", "alguien de la oficina", etc.
-Excluye referencias a Lumi como "Lumi", "la asistente", "mi asistente", etc.
-Excluye referencias al receptor como "tu", "ti", "te", "usted", etc.
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

    turns = get_recent_session_log(sid, limit=1)
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

def _slim_candidates(candidates: list[dict] | None) -> list[dict]:
    """Trim candidate dicts before persisting to candidates_json (drops nested rows)."""
    if not candidates:
        return []
    out = []
    for c in candidates:
        out.append({
            "person_id": c.get("person_id"),
            "display_name": c.get("display_name"),
            "score": c.get("score"),
            "matched_on": c.get("matched_on"),
        })
    return out


async def _resolve_entities(entities: list[dict], user_id: str, message: str) -> list[dict]:
    """Resolve each detected entity against known_persons and assemble context.
    Returns a list parallel to `entities` used for prompt injection and
    post-turn persistence. Self-mentions (entity resolves to speaker) are kept
    in the list (so persistence still records them) but flagged `is_self_mention=True`
    so the formatter skips them."""
    contexts: list[dict] = []
    for entity in entities:
        try:
            resolution = resolve_person_mention(entity, anchor_person_id=user_id)
        except Exception as e:
            logger.warning(f"[resolve] failed for entity={entity.get('raw_text','')!r}: {e}")
            resolution = {
                "status": "unknown",
                "candidates": [],
                "reason": f"resolver error: {e}",
                "mention": entity,
            }

        ctx = {
            "mention": entity,
            "status": resolution.get("status", "unknown"),
            "person_id": resolution.get("person_id"),
            "display_name": resolution.get("display_name"),
            "candidates": resolution.get("candidates", []),
            "reason": resolution.get("reason", ""),
            "raw_name": entity.get("raw_name"),
            "descriptor": entity.get("descriptor"),
            "person": None,
            "relations": [],
            "scoped_memories": [],
            "is_self_mention": False,
        }

        status = ctx["status"]
        pid = ctx.get("person_id")

        # Assistant-leak guard: if Lumi's prior turn used the user's own name
        # (e.g. "Buenas tardes, Jose"), the next-turn transcript carries it and
        # the extractor may attribute the mention to "Lumi". Drop only when
        # both: the speaker is the anchor target AND the resolver pointed back
        # at the user themselves. Third parties Lumi mentions (Gloria, Jose Luis,
        # etc.) keep their normal context fetch + injection.
        anchor_lower = (entity.get("anchor") or "").lower()
        if anchor_lower in ("lumi", "asistente", "assistant") and pid == user_id:
            ctx["is_self_mention"] = True
            logger.info(
                f"[resolve] dropping assistant-name-echo: "
                f"raw={entity.get('raw_text','')[:40]!r}"
            )
            contexts.append(ctx)
            continue

        if status == "resolved" and pid:
            if pid == user_id:
                ctx["is_self_mention"] = True
            else:
                try:
                    ctx["person"] = get_known_person(pid)
                    ctx["relations"] = get_relations(pid) or []
                except Exception as e:
                    logger.warning(f"[resolve] profile/relations fetch failed for {pid}: {e}")
                try:
                    # Modelo C: user_id en Mem0 = person_id del sujeto.
                    # "Qué sé sobre Sosa" => search_relevant(user_id="sosa").
                    ctx["scoped_memories"] = await search_relevant(
                        user_id=pid, query=message,
                        limit=3, min_score=0.5,
                    )
                except Exception as e:
                    logger.warning(f"[resolve] scoped Mem0 failed for {pid}: {e}")
        elif status == "candidate_unconfirmed" and pid:
            try:
                ctx["person"] = get_known_person(pid)
            except Exception as e:
                logger.warning(f"[resolve] profile fetch failed for {pid}: {e}")

        logger.info(
            f"[resolve] raw={entity.get('raw_text','')[:40]!r} "
            f"status={status} person={pid} self={ctx['is_self_mention']}"
        )
        contexts.append(ctx)

    return contexts


# Inicializar bases de datos al importar
init_databases()
init_state_table()
logger.info("core orchestrator initialized")

CACHE_KEY_CHAT = os.getenv("PROMPT_CACHE_KEY_CHAT")
CACHE_KEY_TOOL = os.getenv("PROMPT_CACHE_KEY_TOOL")
CACHE_KEY_ENTITY = os.getenv("PROMPT_CACHE_KEY_ENTITY")


def _get_sid(metadata: dict) -> str:
    return metadata.get("session_id", "default")


def _finalize_turn(
    user_id: str,
    message: str,
    reply_text: str,
    sid: str,
    entities: list[dict] | None = None,
    entities_context: list[dict] | None = None,
):
    history_id = save_turn(user_id, "user", message, sid)
    save_turn(user_id, "assistant", reply_text, sid)

    touch_last_interaction()

    if not entities:
        return

    for i, entity in enumerate(entities):
        row = add_mention(entity, history_id=history_id, user_id=user_id, session_id=sid)
        if not row:
            continue
        ctx = entities_context[i] if entities_context and i < len(entities_context) else None
        if not ctx:
            continue
        try:
            update_mention_resolution(
                mention_id=row["mention_id"],
                status=ctx.get("status", "unknown"),
                resolved_person_id=ctx.get("person_id"),
                candidates=_slim_candidates(ctx.get("candidates")),
            )
        except Exception as e:
            logger.warning(f"[finalize] update_mention_resolution failed: {e}")
        # mention_count / last_mentioned on known_persons are bumped by the
        # nightly consolidator (consolidate_entity_mentions). Per-turn we only
        # persist the raw + resolved mention row.


# ═══════════════════════════════════════════════════════════════════════════════
# Entry points
# ═══════════════════════════════════════════════════════════════════════════════

async def cycle(user_id: str, message: str, metadata: dict):
    from agent.affect.mood import get_sleep_stage, LUMI_TZ_OFFSET

    if get_sleep_stage(timezone(timedelta(hours=LUMI_TZ_OFFSET))) == "sleeping":
        yield "[tired] Zzz..."
        return

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
    entities_context = await _resolve_entities(entities, user_id, message) if entities else []
    logger.info(f"[entities] detected {len(entities)} entities with context: {[{'raw_text': e.get('raw_text','')[:30], 'status': c.get('status'), 'person_id': c.get('person_id')} for e, c in zip(entities, entities_context)]}")
    messages = await build_messages(user_id, message, metadata, entities_context=entities_context)

    tool, args = await intention.decide_tool(sid, message, user_id=user_id)#, prompt_cache_key=CACHE_KEY_TOOL)
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
    async for chunk in chat_stream(messages,reasoning_effort="low", prompt_cache_key=CACHE_KEY_CHAT):
        full_reply += chunk
        yield chunk

    _finalize_turn(user_id, message, full_reply, sid, entities=entities, entities_context=entities_context)


async def run_stream(user_id: str, message: str, metadata: dict):
    async for chunk in cycle(user_id, message, metadata):
        yield chunk


async def run(user_id: str, message: str, metadata: dict) -> str:
    full = ""
    async for chunk in cycle(user_id, message, metadata):
        full += chunk
    return full
