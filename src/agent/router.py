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

_EXPLICIT_SAVE_TRIGGERS = [
    # Verb forms: imperative (tú/usted), subjunctive, infinitive
    r"\b(guarda|guardar|guarde|guardes|guárdam?e?l?a?o?s?)\b",
    r"\b(anota|anotar|anote|anotes|anótam?e?l?a?o?s?)\b",
    r"\b(recuerda|recordar|recuerde|recuerdes|recuérdam?e?l?a?o?s?)\b",
    r"\b(apunta|apuntar|apunte|apuntes|apúntam?e?l?a?o?s?)\b",
    r"\b(memoriza|memorizar|memorice|memorices)\b",
    # Phrasal patterns: "que lo/la guarde", "necesito que anotes"
    r"\b(que (la|lo|las|los|me|te) (guardes?|guardar|anotes?|anotar|recuerdes?|apuntes?))\b",
    r"\b(necesito que|quiero que|puedes|podrías) (guard|anot|record|apunt)\w*\b",
    r"\b(no se (me|te) olvide|para que no se (me|te) olvide)\b",
]

def _matches(text: str, patterns: list[str]) -> bool:
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


def classify(message: str) -> str:
    """
    Retorna:
      'web_search'   → necesita informacion externa actual
      'long_task'    → tarea que toma tiempo, respuesta inmediata + async
      'explicit_save' → guarda verbatim sin extractor LLM
      'chat'         → conversacion normal, loop estandar
    """
    blocked = _matches(message, _WEB_SEARCH_BLOCKLIST)

    if _matches(message, _LONG_TASK_TRIGGERS):
        return "long_task"

    if _matches(message, _EXPLICIT_SAVE_TRIGGERS):
        return "explicit_save"

    if not blocked and _matches(message, _WEB_SEARCH_TRIGGERS):
        return "web_search"

    return "chat"


_CATEGORY_PATTERNS = [
    (r"\b(receta|ingredientes|cocina|preparar|comida)\b", "recipe"),
    (r"\b(https?://|link|url|enlace|página)\b", "link"),
    (r"\b(código|script|función|clase|programa|comando|code)\b", "code"),
    (r"\b(referencia|fuente|cita|bibliografía|paper|artículo)\b", "reference"),
]


def detect_category(message: str) -> str:
    """Classify an explicit save into metadata category.
    Returns one of: recipe, link, note, code, reference."""
    text = message.lower()
    for pattern, cat in _CATEGORY_PATTERNS:
        if re.search(pattern, text):
            return cat
    return "note"
