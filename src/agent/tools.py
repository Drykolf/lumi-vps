"""
ToolRegistry — soporta tools locales (VPS) y remotas (bridge).
Fase 3: tools basicas + infraestructura para bridge.
"""
import logging
from src.bridge import bridge_server

logger = logging.getLogger("tools")

# ── Registry ──────────────────────────────────────────────────────────────────

_local_tools: dict[str, callable] = {}
_remote_tools: dict[str, dict] = {}  # name -> schema


def register_local(name: str, fn: callable):
    _local_tools[name] = fn


def register_remote(name: str, schema: dict):
    _remote_tools[name] = schema


def all_schemas() -> list[dict]:
    """Lo que ve el LLM — no distingue local de remote."""
    return list(_remote_tools.values())


def has_tool_calls(message: dict) -> bool:
    return bool(message.get("tool_calls"))


async def execute(tool_calls: list, user_id: str) -> list[dict]:
    results = []
    for call in tool_calls:
        name = call.get("function", {}).get("name")
        args = call.get("function", {}).get("arguments", {})

        if name in _local_tools:
            try:
                result = await _local_tools[name](**args)
            except Exception as e:
                result = {"error": str(e)}
        elif name in _remote_tools:
            result = await bridge_server.call_remote(user_id, name, args)
        else:
            result = {"error": f"tool '{name}' no registrada"}

        logger.info(f"tool={name} user={user_id} result={result}")
        results.append({"tool": name, "result": result})

    return results


# ── Tools locales VPS ─────────────────────────────────────────────────────────

from datetime import datetime, timezone, timedelta

COL = timezone(timedelta(hours=-5))

async def _get_current_time() -> dict:
    now = datetime.now(COL)
    return {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "COT (UTC-5)",
        "weekday": now.strftime("%A"),
    }

# ── Registro de tools ────────────────────────────────────────────────────────
register_local("get_current_time", _get_current_time)
register_remote("get_clipboard", {
    "type": "function",
    "function": {
        "name": "get_clipboard",
        "description": "Obtiene el contenido actual del clipboard del PC de Jose.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }
})