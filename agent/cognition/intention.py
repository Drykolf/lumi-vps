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
from agent.memory import get_recent_session_log
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

async def _tool_check(sid: str, message: str, user_id: str = "user", prompt_cache_key: str | None = None) -> str | None:
    """Returns tool name if one is needed, None otherwise. ~500 tokens."""
    all_schemas_ = all_schemas()
    if not all_schemas_:
        return None

    tool_lines = []
    for s in all_schemas_:
        name = s["function"]["name"]
        desc = s["function"].get("description", name)
        tool_lines.append(f"  '{name}': {desc}")

    tools_text = "\n".join(tool_lines)

    turns = get_recent_session_log(sid, include_summarized=True, limit=6)
    transcript = ""
    for t in turns:
        speaker = "Lumi" if t["role"] == "assistant" else (t.get("user_id") or user_id)
        transcript += f"{speaker}: {t['content']}\n"
    transcript += f"{user_id}: {message}"

    system_prompt = (
        "Eres el router de herramientas de Lumi.\n"
        "Tu tarea NO es responder al usuario. Tu única tarea es decidir si antes de responder "
        "hace falta llamar una herramienta.\n\n"

        "Herramientas disponibles, formato nombre: descripción.\n"
        "Usa el nombre EXACTO de la herramienta. No traduzcas nombres.\n\n"
        f"{tools_text}\n\n"

        "Salida obligatoria, exactamente una línea:\n"
        "- SI:nombre_exacto\n"
        "- NO\n\n"

        "Criterio de decisión:\n"
        "1. Interpreta el mensaje actual usando el contexto reciente. Resuelve referencias como "
        "'eso', 'lo', 'búscalo', 'investígalo', 'ese juego', 'esa persona', etc.\n"
        "2. Elige una herramienta solo si su descripción cubre exactamente la fuente o acción necesaria.\n"
        "3. Si el usuario pide explícitamente buscar, investigar, verificar, consultar, revisar en internet, "
        "mirar en la web, googlear, o dice 'búscalo' / 'busquelo', usa la herramienta de búsqueda web disponible.\n"
        "4. Usa una herramienta cuando la respuesta dependa de información externa, actual, cambiante o difícil "
        "de saber sin consultar una fuente: noticias, precios, clima, eventos, lanzamientos, juegos, productos, "
        "empresas, personas públicas, fechas, disponibilidad, versiones, resultados, leyes o datos recientes.\n"
        "5. Para entidades externas desconocidas o de nicho, como juegos, apps, productos, empresas, libros, "
        "películas, eventos o personas públicas, usa búsqueda web si el usuario pregunta qué son, si existen, "
        "de qué tratan, estado actual, fecha, precio, noticias u opiniones.\n"
        "6. No uses herramientas para charla casual, traducción, redacción, explicación general, razonamiento, "
        "ayuda emocional o información que ya está claramente en el contexto.\n"
        "7. No uses herramientas de portapapeles/clipboard salvo que el usuario mencione explícitamente "
        "portapapeles, clipboard, copiado, pegado, 'lo que copié', 'mi clipboard' o equivalente.\n"
        "8. Nunca elijas una herramienta por similitud superficial de palabras. Elige por intención y fuente.\n"
        "9. Si dudas entre una herramienta claramente solicitada por el usuario y NO, usa la herramienta.\n"
        "10. Si dudas entre una herramienta no relacionada y NO, responde NO.\n\n"

        "Ejemplos:\n"
        "Contexto: El usuario preguntó por 'Limit Zero Breakers' y Lumi dijo que no le sonaba.\n"
        "Usuario: busquelo y me cuenta de q trata\n"
        "Respuesta: SI:web_search\n\n"

        "Usuario: busca noticias recientes de Nintendo\n"
        "Respuesta: SI:web_search\n\n"

        "Usuario: y ese juego de qué trata?\n"
        "Contexto: Se está hablando de un juego desconocido o reciente.\n"
        "Respuesta: SI:web_search\n\n"

        "Usuario: qué hay en mi portapapeles?\n"
        "Respuesta: SI:get_clipboard\n\n"

        "Usuario: usa el texto que copié y resumelo\n"
        "Respuesta: SI:get_clipboard\n\n"

        "Usuario: cuéntame un chiste\n"
        "Respuesta: NO\n\n"

        "Usuario: traduce esto al inglés: hola, cómo estás\n"
        "Respuesta: NO\n\n"

        "Usuario: quién es Juan?\n"
        "Contexto: Juan fue mencionado antes como amigo del usuario.\n"
        "Respuesta: NO\n\n"

        "Usuario: quién es el presidente actual de Argentina?\n"
        "Respuesta: SI:web_search\n"
    )
    try:
        response = await chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            max_tokens=20,
            temperature=0.1,
            reasoning_effort="none",
            model_group=ModelGroup.LIGHTWEIGHT,
            prompt_cache_key=prompt_cache_key,
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


async def _formulate_query(message: str, tool_name: str, sid: str, prompt_cache_key: str | None = None) -> dict | None:
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

    turns = get_recent_session_log(sid, include_summarized=True, limit=6)
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
            prompt_cache_key=prompt_cache_key,
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


async def decide_tool(sid: str, message: str, user_id: str = "user", prompt_cache_key: str | None = None) -> tuple[str | None, dict | None]:
    """One-stop: check if tool needed + generate args. Returns (tool_name, args)."""
    tool = await _tool_check(sid, message, user_id=user_id, prompt_cache_key=prompt_cache_key)
    if tool:
        args = await _formulate_query(message, tool, sid, prompt_cache_key=prompt_cache_key)
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
