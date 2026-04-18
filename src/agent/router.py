"""
Clasificador pre-loop — sección 3.3 y loop del manual.
Decide qué hacer con el input ANTES de llamar al LLM.

Fase 3: clasificador por keywords (capa 1 del híbrido en cascada).
Fase 4+: agregar semantic router con embeddings.
"""
import re

# ── Keywords para búsqueda web ────────────────────────────────────────────────
_WEB_SEARCH_TRIGGERS = [
    r"\b(qué pasó|qué paso|noticias|precio|cotización|dólar|euro|bitcoin|btc)\b",
    r"\b(hoy|ahorita|ahora mismo|en este momento|actualmente)\b",
    r"\b(busca|búscame|buscar|googlea|investiga)\b",
    r"\b(clima|temperatura|tiempo en)\b",
    r"\b(último|última|reciente|nuevo|nueva)\b",
]

# ── Keywords para tareas largas ───────────────────────────────────────────────
_LONG_TASK_TRIGGERS = [
    r"\b(analiza|analizar|análisis completo|resume|resumir|redacta|escribir)\b",
    r"\b(investiga a fondo|investigación|compara|comparar|explica en detalle)\b",
    r"\b(crea un|crear un|genera un|genera una|planea|planear)\b",
]

# ── Frases que NUNCA deben disparar búsqueda web ─────────────────────────────
_WEB_SEARCH_BLOCKLIST = [
    r"\b(hola|cómo estás|qué tal|cómo va|cómo te sientes)\b",
    r"\b(me siento|estoy (bien|mal|cansado|feliz|triste))\b",
    r"\b(gracias|ok|listo|entendido|perfecto)\b",
]


def _matches(text: str, patterns: list[str]) -> bool:
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


def classify(message: str) -> str:
    """
    Retorna:
      'web_search'  → necesita información externa actual
      'long_task'   → tarea que toma tiempo, respuesta inmediata + async
      'chat'        → conversación normal, loop estándar
    """
    if _matches(message, _WEB_SEARCH_BLOCKLIST):
        return "chat"

    if _matches(message, _LONG_TASK_TRIGGERS):
        return "long_task"

    if _matches(message, _WEB_SEARCH_TRIGGERS):
        return "web_search"

    return "chat"
