"""
Core orchestrator — clasificar → handler → contexto → tools → LLM → retornar.
"""
import asyncio
import json
import re

from agent.cognition import attention, intention
from agent.cognition.stimulus import handle_long_task, handle_explicit_save, handle_web_search
from agent.expression.synapses import chat, chat_stream
from agent.cognition.working_memory import build_messages
from agent.memory.recall import save_turn, init_databases, record_turn, generate_summary, reset_turns, get_session_turns, add_memory
from agent.affect.state import init_state_table
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


async def _extract_facts(user_id: str, user_msg: str, lumi_reply: str):
    """Fire-and-forget: send the turn to Mem0 for fact extraction."""
    await add_memory(
        [
            {"role": "user", "content": user_msg},
        ],
        user_id,
    )


def _finalize_turn(user_id: str, message: str, reply_text: str, sid: str):
    save_turn(user_id, "user", message, sid)
    save_turn(user_id, "assistant", reply_text, sid)
    _maybe_summarize(sid, user_id)


# ── Lightweight tool check ─────────────────────────────────────────────────────

async def _tool_check(sid: str, message: str) -> str | None:
    """Returns tool name if one is needed, None otherwise. ~500 tokens."""
    all_schemas = intention.all_schemas()
    if not all_schemas:
        return None

    tool_lines = []
    for s in all_schemas:
        name = s["function"]["name"]
        desc = s["function"].get("description", name)
        tool_lines.append(f"  '{name}': {desc}")

    turns = get_session_turns(sid, include_summarized=True, limit=10)
    transcript = ""
    for t in turns:
        role = "Jose" if t["role"] == "user" else "Lumi"
        transcript += f"{role}: {t['content']}\n"
    transcript += f"Jose: {message}"

    prompt = (
        "Herramientas disponibles (usa el nombre EXACTO, no lo traduzcas):\n"
        f"{"\n".join(tool_lines)}\n\n"
        "Responde SOLO 'SI:nombre_exacto' si necesitas una herramienta, o 'NO' si no."
    )
    try:
        response = await chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": transcript},
            ],
            max_tokens=20,
        )
        content = response.get("content", "").strip()
        logger.info(f"[tool_check] response: {content}")

        if content.upper().startswith("SI:"):
            name = content.split(":", 1)[1].strip()
            if any(s["function"]["name"] == name for s in all_schemas):
                return name
    except Exception as e:
        logger.warning(f"[tool_check] failed: {e}")
    return None


async def _formulate_query(message: str, tool_name: str, sid: str) -> dict | None:
    """Lightweight: generate tool arguments from conversation context. ~200 tokens."""
    all_schemas = intention.all_schemas()
    schema = next((s for s in all_schemas if s["function"]["name"] == tool_name), None)
    if not schema:
        return None

    param_props = schema["function"]["parameters"].get("properties", {})
    param_names = list(param_props.keys())

    # No params needed → execute directly, no LLM call
    if not param_names:
        return {}

    # Build tool-biased prompt from schema
    desc_lines = []
    for p in param_names:
        pinfo = param_props[p]
        desc_lines.append(f"'{p}' ({pinfo.get('type', 'string')}): {pinfo.get('description', p)}")

    turns = get_session_turns(sid, include_summarized=True, limit=6)
    transcript = ""
    for t in turns:
        role = "Jose" if t["role"] == "user" else "Lumi"
        transcript += f"{role}: {t['content']}\n"
    transcript += f"Jose: {message}"

    prompt = (
        f"Genera argumentos para la herramienta '{tool_name}'. "
        f"Parametros: {'; '.join(desc_lines)}. "
        f"Responde SOLO con JSON: {{{', '.join(f'\"{p}\": ...' for p in param_names)}}}"
    )

    try:
        response = await chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": transcript},
            ],
            max_tokens=100,
        )
        content = response.get("content", "").strip()
        logger.info(f"[formulate_query] {tool_name} → {content[:100]}")
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        logger.warning(f"[formulate_query] failed: {e}")
    return None


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

    if task_type == "web_search":
        handle_web_search(metadata)

    messages = await build_messages(user_id, message, metadata)

    tool = await _tool_check(sid, message)
    if tool:
        args = await _formulate_query(message, tool, sid)
        if args is not None:
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
    #asyncio.create_task(_extract_facts(user_id, message, full_reply))


async def run_stream(user_id: str, message: str, metadata: dict):
    async for chunk in cycle(user_id, message, metadata):
        yield chunk


async def run(user_id: str, message: str, metadata: dict) -> str:
    full = ""
    async for chunk in cycle(user_id, message, metadata):
        full += chunk
    return full