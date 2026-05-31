"""
Core orchestrator — clasificar → handler → contexto → tools → LLM → retornar.
"""
import asyncio
import json
import os
from datetime import timezone, timedelta

from agent.cognition import attention, intention
from agent.cognition.frame import turn_frame_check
from agent.cognition.memory_plan import resolve_memory_plan
from agent.cognition.stimulus import handle_long_task, handle_explicit_save
from agent.expression.synapses import chat_stream
from agent.cognition.working_memory import build_messages
from agent.cognition import context_governor
from agent.cognition.context_policy import memory_queries_from_frame
from agent.memory import (
    save_turn,
    init_databases,
    add_mention,
    update_mention_resolution,
    resolve_person_mention,
    get_known_person,
    get_relations,
)
from agent.affect import init_state_table, touch_last_interaction
from agent.substrate.logger import get_logger

logger = get_logger("agent.core")


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


async def _resolve_entities(entities: list[dict], user_id: str) -> list[dict]:
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
                # Scoped Mem0 search ahora la hace resolve_memory_plan() según
                # los entity_scoped_queries del frame.
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
CACHE_KEY_FRAME = os.getenv("PROMPT_CACHE_KEY_FRAME")


def _get_cid(metadata: dict) -> str:
    return metadata.get("channel_id", "default")


def _persist_mentions(
    entities: list[dict],
    entities_context: list[dict],
    history_id: int,
    user_id: str,
    cid: str,
) -> None:
    """Save detected entity mentions + their resolution context to person_mentions."""
    for i, entity in enumerate(entities):
        row = add_mention(entity, history_id=history_id, user_id=user_id, channel_id=cid)
        if not row:
            continue
        ctx = entities_context[i] if i < len(entities_context) else None
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


def _finalize_turn(
    user_id: str,
    message: str,
    reply_text: str,
    cid: str,
    entities: list[dict] | None = None,
    entities_context: list[dict] | None = None,
):
    history_id = save_turn(user_id, "user", message, cid)
    save_turn(user_id, "assistant", reply_text, cid)

    touch_last_interaction()

    if entities:
        _persist_mentions(entities, entities_context or [], history_id, user_id, cid)
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

    #task_type = attention.classify(message)
    task_type = "chat"
    #logger.info(f"[classify] task_type={task_type} | msg_preview={message[:80]}")
    cid = _get_cid(metadata)

    """if task_type == "long_task":
        reply = await handle_long_task(user_id, message, cid)
        _finalize_turn(user_id, message, reply, cid)
        yield reply
        return

    if task_type == "explicit_save":
        reply = await handle_explicit_save(user_id, message, cid, metadata)
        _finalize_turn(user_id, message, reply, cid)
        yield reply
        return"""

    frame = await turn_frame_check(user_id, message, cid, metadata, prompt_cache_key=CACHE_KEY_FRAME)
    entities = frame["entities"]
    entities_context = await _resolve_entities(entities, user_id) if entities else []
    logger.info(f"[entities] detected {len(entities)} entities with context: {[{'raw_text': e.get('raw_text','')[:30], 'status': c.get('status'), 'person_id': c.get('person_id')} for e, c in zip(entities, entities_context)]}")
    memory_results = await resolve_memory_plan(user_id, frame["memory_plan"], entities_context)
    messages = await build_messages(
        user_id, message, metadata,
        entities_context=entities_context,
        memory_results=memory_results,
        conversation_mode=frame["conversation_mode"],
        user_emotion=frame["user_emotion"],
        style_capsule=frame["style_capsule"],
        memory_queries=memory_queries_from_frame(frame),
    )

    # Frame audit: veredicto del frame por turno para la matriz de confusión.
    # La selección/recorte real ya la hizo build_messages; el presupuesto real
    # se loguea en dynamic.log.
    try:
        context_governor.log_frame_audit(user_id, message, frame)
    except Exception as e:
        logger.warning(f"[frame-audit] {e}")

    plan = frame["tool_plan"]
    if plan["needs_tool"] and plan["tool_name"] and isinstance(plan["args"], dict):
        tool_name = plan["tool_name"]
        args = plan["args"]
        tool_call = [{"function": {"name": tool_name, "arguments": json.dumps(args, ensure_ascii=False)}}]
        tool_results = await intention.execute(tool_call, user_id)
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": tool_name, "arguments": json.dumps(args, ensure_ascii=False)}}],
        })
        for r in tool_results:
            messages.append({"role": "tool", "tool_call_id": "call_1", "content": str(r.get("result", ""))})

    full_reply = ""
    async for chunk in chat_stream(messages,prompt_cache_key=CACHE_KEY_CHAT):#reasoning_effort="medium", 
        full_reply += chunk
        yield chunk

    _finalize_turn(user_id, message, full_reply, cid, entities=entities, entities_context=entities_context)


async def run_stream(user_id: str, message: str, metadata: dict):
    async for chunk in cycle(user_id, message, metadata):
        yield chunk


async def run(user_id: str, message: str, metadata: dict) -> str:
    full = ""
    async for chunk in cycle(user_id, message, metadata):
        full += chunk
    return full


async def observe_turn(user_id: str, message: str, cid: str) -> None:
    """Save an observed group-chat message and run lightweight entity extraction.

    Called as a background task for messages LUMI witnessed but did not respond
    to. Saves the turn to history and detects third-party mentions so the nightly
    quiescence step 1 can resolve them. The speaker's own evaluation is handled
    at quiescence time by inspecting history directly (see consolidation.py).
    """
    history_id = save_turn(user_id, "user", message, cid)
    try:
        frame = await turn_frame_check(user_id, message, cid, metadata={})
        entities = frame["entities"]
        if entities:
            entities_context = await _resolve_entities(entities, user_id)
            _persist_mentions(entities, entities_context, history_id, user_id, cid)
    except Exception as e:
        logger.warning(f"[observe_turn] frame check failed: {e}")
