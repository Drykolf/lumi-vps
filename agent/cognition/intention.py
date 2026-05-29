"""
Intention module — tool registry facade.

Tool routing y formulación de argumentos viven ahora en agent/cognition/frame.py
dentro de `turn_frame_check()`. Este módulo sólo expone la API pública del
registro de tools y el dispatcher.
"""
from agent.faculties.registry import (
    register_tool,
    register_remote,
    all_schemas,
    _local_tools,
    _remote_tools,
)
from agent.faculties.dispatcher import execute
from agent.faculties.brave_search import BraveSearchTool


def has_tool_calls(message: dict) -> bool:
    return bool(message.get("tool_calls"))


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
