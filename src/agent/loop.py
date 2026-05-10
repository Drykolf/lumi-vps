"""
Orquestador principal — sección 2.2 y loop del manual.
Ciclo: clasificar → contexto → LLM → tools → memoria → retornar.
"""
import asyncio

from src.agent import router, tools
from src.llm.factory import chat, chat_stream
from src.agent.context import build_messages
from src.memory.facade import save_turn, init_db, init_core_db, add_memory_explicit, record_turn, generate_summary, reset_turns, process_explicit_memory
from src.state.internal_state import init_state_table

from src.utils.logger import get_logger

logger = get_logger("agent.loop")

MAX_ITERATIONS = 10

# Inicializar tablas al importar
init_db()
init_core_db()
init_state_table()
logger.info("loop module initialized — explicit_save logging active")

_CATEGORY_NAMES = {
    "recipe": "receta", "link": "enlace", "note": "nota",
    "code": "codigo", "reference": "referencia",
}


def _inject_save_verification(messages: list[dict], result: dict, category: str):
    """Prepend save verification to the system prompt so Lumi responds dynamically."""
    cat_name = _CATEGORY_NAMES.get(category, category)
    if result.get("success"):
        saved = result.get("memory", "")[:300]
        msg = (
            f"[Sistema interno: El mensaje del usuario fue guardado en Mem0 "
            f"como {cat_name}. Contenido: {saved}. "
            f"Confirma el guardado de forma natural, en tu voz.]"
        )
    else:
        msg = (
            "[Sistema interno: El intento de guardar en Mem0 fallo. "
            "El servicio de memoria no esta disponible. "
            "Informa al usuario con honestidad, sin alarmismo.]"
        )
    messages[0]["content"] = msg + "\n\n" + messages[0]["content"]


async def _run_summary(session_id: str):
    """Fire-and-forget: generate summary then reset turn counter."""
    await generate_summary(session_id)
    reset_turns(session_id)


def _get_sid(metadata: dict) -> str:
    return metadata.get("session_id", "default")


async def _handle_long_task(user_id: str, message: str, sid: str) -> str:
    save_turn(user_id, "user", message, sid)
    reply = "[thinking] Dame un momento, esto toma un poco mas de tiempo."
    save_turn(user_id, "assistant", reply, sid)
    return reply


async def _handle_explicit_save(user_id: str, message: str, sid: str, metadata: dict) -> str:
    category = router.detect_category(message)
    logger.info(f"[explicit_save] category={category} | user_id={user_id}")
    processed = await process_explicit_memory(message)
    result = await add_memory_explicit(processed["memory"], user_id, processed.get("category", category))
    save_turn(user_id, "user", message, sid)
    logger.info(f"[explicit_save] saved to Mem0 | success={result.get('success')} | category={result.get('category')}")
    messages = await build_messages(user_id, message, metadata)
    _inject_save_verification(messages, result, processed.get("category", category))
    response_msg = await chat(messages)
    reply_text = response_msg.get("content", "")
    if not reply_text:
        cat_name = _CATEGORY_NAMES.get(processed.get("category", category), "eso")
        reply_text = f"[neutral] Listo, guarde {cat_name} en mi memoria."
    save_turn(user_id, "assistant", reply_text, sid)
    _maybe_summarize(sid, user_id)
    logger.info(f"[explicit_save] response | reply_len={len(reply_text)} | preview={reply_text[:80]}")
    return reply_text


async def _run_tool_loop(messages: list[dict], user_id: str) -> tuple[list[dict], str | None]:
    schemas = tools.all_schemas()
    for _ in range(MAX_ITERATIONS):
        response_msg = await chat(messages, tool_schemas=schemas or None)
        reply_text = response_msg.get("content", "")

        if tools.has_tool_calls(response_msg):
            raw_calls = response_msg.get("tool_calls") or []
            tool_calls = [
                {
                    "function": {
                        "name": tc.function.name if hasattr(tc, "function") else tc.get("function", {}).get("name"),
                        "arguments": tc.function.arguments if hasattr(tc, "function") else tc.get("function", {}).get("arguments", {}),
                    }
                }
                for tc in raw_calls
            ]
            tool_results = await tools.execute(tool_calls, user_id)
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in response_msg.get("tool_calls", [])
                ],
            })
            for tc, result in zip(response_msg.get("tool_calls", []), tool_results):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result.get("result", "")),
                })
            continue

        if "[ESCALAR]" in reply_text:
            reply_text = reply_text.replace("[ESCALAR]", "").strip()
        if "[SEGUIMIENTO:" in reply_text:
            pass

        return messages, reply_text
    return messages, None


def _finalize_turn(user_id: str, message: str, reply_text: str, sid: str):
    save_turn(user_id, "user", message, sid)
    save_turn(user_id, "assistant", reply_text, sid)
    _maybe_summarize(sid, user_id)


def _maybe_summarize(sid: str, user_id: str):
    turn_count = record_turn(sid, user_id)
    # TODO: heartbeat — trigger summary after 1h inactivity per session (time-based)
    if turn_count % 5 == 0:
        asyncio.create_task(_run_summary(sid))


# ═══════════════════════════════════════════════════════════════════════════════
# Entry points
# ═══════════════════════════════════════════════════════════════════════════════

async def run_stream(user_id: str, message: str, metadata: dict):
    task_type = router.classify(message)
    logger.info(f"[classify] task_type={task_type} | msg_preview={message[:80]}")
    sid = _get_sid(metadata)

    if task_type == "long_task":
        reply = await _handle_long_task(user_id, message, sid)
        yield reply
        return

    if task_type == "explicit_save":
        reply = await _handle_explicit_save(user_id, message, sid, metadata)
        yield reply
        return

    if task_type == "web_search":
        metadata["web_search_needed"] = True

    messages = await build_messages(user_id, message, metadata)
    messages, _reply = await _run_tool_loop(messages, user_id)

    full_reply = ""
    async for chunk in chat_stream(messages):
        full_reply += chunk
        yield chunk

    _finalize_turn(user_id, message, full_reply, sid)


async def run(user_id: str, message: str, metadata: dict) -> str:
    task_type = router.classify(message)
    logger.info(f"[classify] task_type={task_type} | msg_preview={message[:80]}")
    sid = _get_sid(metadata)

    if task_type == "long_task":
        return await _handle_long_task(user_id, message, sid)

    if task_type == "explicit_save":
        return await _handle_explicit_save(user_id, message, sid, metadata)

    if task_type == "web_search":
        metadata["web_search_needed"] = True

    messages = await build_messages(user_id, message, metadata)
    _messages, reply = await _run_tool_loop(messages, user_id)
    if reply is None:
        reply = "[neutral] No logre resolver esto en el tiempo esperado."

    _finalize_turn(user_id, message, reply, sid)
    return reply
