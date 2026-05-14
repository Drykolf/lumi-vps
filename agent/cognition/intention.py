"""
Intention detection — determines if/what tool is needed and with what arguments.
Cognition decides intent; faculties execute it.

Backward-compat re-exports: register_tool, register_remote, all_schemas, execute.
New: _tool_check, _formulate_query, decide_tool, has_tool_calls.
"""
import re
import json
import logging
from agent.expression.synapses import chat, ModelGroup
from agent.memory import get_session_turns
from agent.faculties.registry import (
    register_tool,
    register_remote,
    all_schemas,
    _local_tools,
    _remote_tools,
)
from agent.faculties.dispatcher import execute
from agent.faculties.brave_search import BraveSearchTool

logger = logging.getLogger("tools")


def has_tool_calls(message: dict) -> bool:
    return bool(message.get("tool_calls"))


# ── Lightweight tool check ─────────────────────────────────────────────────────

async def _tool_check(sid: str, message: str) -> str | None:
    """Returns tool name if one is needed, None otherwise. ~500 tokens."""
    all_schemas_ = all_schemas()
    if not all_schemas_:
        return None

    tool_lines = []
    for s in all_schemas_:
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
        "Responde SOLO 'SI:nombre_exacto' si necesitas una herramienta, o 'NO' si no.\n\n"
        "Guia:\n"
        "- Usa web_search SOLO para informacion objetiva y actualizada (noticias, precios, eventos, clima, datos que cambian).\n"
        "- NO uses web_search para nombres de personas, recuerdos personales, o conversacion casual.\n"
        "- Usa get_clipboard SOLO si el usuario pide explicitamente algo del portapapeles.\n"
        "- Si puedes responder con lo que sabes o con el contexto de la conversacion, responde NO."
    )
    try:
        response = await chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": transcript},
            ],
            max_tokens=20,
            temperature=0.1,
            reasoning_effort="none",
            model_group=ModelGroup.LIGHTWEIGHT,
        )
        content = response.get("content", "").strip()
        logger.info(f"[tool_check] response: {content}")

        if content.upper().startswith("SI:"):
            name = content.split(":", 1)[1].strip()
            if any(s["function"]["name"] == name for s in all_schemas_):
                return name
    except Exception as e:
        logger.warning(f"[tool_check] failed: {e}")
    return None


async def _formulate_query(message: str, tool_name: str, sid: str) -> dict | None:
    """Lightweight: generate tool arguments from conversation context. ~200 tokens."""
    all_schemas_ = all_schemas()
    schema = next((s for s in all_schemas_ if s["function"]["name"] == tool_name), None)
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
            temperature=0.1,
            reasoning_effort="none",
            model_group=ModelGroup.LIGHTWEIGHT,
        )
        content = response.get("content", "").strip()
        logger.info(f"[formulate_query] {tool_name} → {content[:100]}")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*?\}", content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        logger.warning(f"[formulate_query] failed: {e}")
    return None


async def decide_tool(sid: str, message: str) -> tuple[str | None, dict | None]:
    """One-stop: check if tool needed + generate args. Returns (tool_name, args)."""
    tool = await _tool_check(sid, message)
    if tool:
        args = await _formulate_query(message, tool, sid)
        return tool, args
    return None, None


# ── Register tools at import time ─────────────────────────────────────────────
register_tool(BraveSearchTool())
register_remote("get_clipboard", {
    "type": "function",
    "function": {
        "name": "get_clipboard",
        "description": "Obtiene el contenido actual del clipboard del PC de Jose.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }
})
