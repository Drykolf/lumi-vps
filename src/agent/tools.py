"""
ToolRegistry — soporta tools locales (VPS) y remotas (bridge).
Fase 3: tools basicas + infraestructura para bridge.
"""
import logging
from src.bridge import bridge_server
from src.mcp_servers.brave_search.search import search as _brave_search
import json as _json

logger = logging.getLogger("tools")

# ── Registry ──────────────────────────────────────────────────────────────────

_local_tools: dict[str, callable] = {}
_remote_tools: dict[str, dict] = {}  # name -> schema


def register_local(name: str, fn: callable):
    _local_tools[name] = fn


def register_remote(name: str, schema: dict):
    _remote_tools[name] = schema


def all_schemas() -> list[dict]:
    schemas = {}
    # Primero locales con schema auto-generado
    for name, fn in _local_tools.items():
        schemas[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": fn.__doc__ or "",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }
        }
    # Remotas sobreescriben si hay conflicto (schema explícito gana)
    for name, schema in _remote_tools.items():
        schemas[name] = schema
    return list(schemas.values())


def has_tool_calls(message: dict) -> bool:
    return bool(message.get("tool_calls"))


async def execute(tool_calls: list, user_id: str) -> list[dict]:
    results = []
    for call in tool_calls:
        name = call.get("function", {}).get("name")
        raw_args = call.get("function", {}).get("arguments", {})
        args = _json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        logger.info(f"tool={name} args={args}")
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

async def _web_search(query: str) -> dict:
    """Busca información actual en la web. Usar cuando el usuario pregunta por noticias, precios, eventos recientes o cualquier dato que pueda haber cambiado."""
    results = await _brave_search(query)
    return {"results": results}

#register_local("web_search", _web_search)
_local_tools["web_search"] = _web_search
_remote_tools["web_search"] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Busca información actual en la web. Usar cuando el usuario pregunta por noticias, precios, eventos recientes o cualquier dato que pueda haber cambiado.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "El término o pregunta a buscar en la web."}
            },
            "required": ["query"]
        }
    }
}
# ── Registro de tools ────────────────────────────────────────────────────────

register_remote("get_clipboard", {
    "type": "function",
    "function": {
        "name": "get_clipboard",
        "description": "Obtiene el contenido actual del clipboard del PC de Jose.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }
})
