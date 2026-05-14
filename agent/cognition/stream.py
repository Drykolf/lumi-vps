"""
Core orchestrator — clasificar → handler → contexto → tools → LLM → retornar.
"""
import asyncio
import json

from agent.cognition import attention, intention
from agent.cognition.stimulus import handle_long_task, handle_explicit_save
from agent.expression.synapses import chat_stream
from agent.cognition.working_memory import build_messages
from agent.memory import save_turn, init_databases, record_turn, generate_summary, reset_turns
from agent.affect import init_state_table
from agent.substrate.logger import get_logger

logger = get_logger("agent.core")

# Inicializar bases de datos al importar
init_databases()
init_state_table()
logger.info("core orchestrator initialized")


def _get_sid(metadata: dict) -> str:
    return metadata.get("session_id", "default")


async def _run_summary(session_id: str):
    await generate_summary(session_id)
    reset_turns(session_id)


def _maybe_summarize(sid: str, user_id: str):
    turn_count = record_turn(sid, user_id)
    if turn_count % 5 == 0:
        asyncio.create_task(_run_summary(sid))


def _finalize_turn(user_id: str, message: str, reply_text: str, sid: str):
    save_turn(user_id, "user", message, sid)
    save_turn(user_id, "assistant", reply_text, sid)
    _maybe_summarize(sid, user_id)


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

    messages = await build_messages(user_id, message, metadata)

    tool, args = await intention.decide_tool(sid, message)
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
    async for chunk in chat_stream(messages):
        full_reply += chunk
        yield chunk

    _finalize_turn(user_id, message, full_reply, sid)


async def run_stream(user_id: str, message: str, metadata: dict):
    async for chunk in cycle(user_id, message, metadata):
        yield chunk


async def run(user_id: str, message: str, metadata: dict) -> str:
    full = ""
    async for chunk in cycle(user_id, message, metadata):
        full += chunk
    return full
