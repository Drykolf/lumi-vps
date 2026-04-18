"""
Registry de herramientas — Fase 3: solo placeholder.
Fase 4+: herramientas reales (Brave Search, bridge local, calendar, etc.)
"""

TOOL_REGISTRY: dict[str, callable] = {}


async def execute(tool_calls: list[dict], user_id: str) -> list[dict]:
    """Ejecuta tool calls del LLM. Retorna resultados."""
    results = []
    for call in tool_calls:
        name = call.get("function", {}).get("name")
        if name in TOOL_REGISTRY:
            result = await TOOL_REGISTRY[name](call, user_id)
            results.append({"tool": name, "result": result})
        else:
            results.append({"tool": name, "result": f"Tool '{name}' no disponible en Fase 3."})
    return results


def has_tool_calls(message: dict) -> bool:
    return bool(message.get("tool_calls"))
