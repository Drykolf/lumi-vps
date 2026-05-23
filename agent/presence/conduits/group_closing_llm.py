"""Mini-LLM que confirma cierre de ventana ENGAGED en grupos de WhatsApp.

Vive en el ciclo de WhatsApp, no en agent/cognition. Cuando el policy
determinista marca un grupo como `pending_close`, esta función decide:
  - si el siguiente mensaje es un cierre real (gracias / chao / listo lumi)
    → responde corto y cierra ventana
  - si el mensaje sigue la conversación → reabre ventana y deja que el LLM
    principal responda normal.
"""
from __future__ import annotations

import re

from agent.expression.synapses import chat, ModelGroup
from agent.substrate.logger import get_logger

logger = get_logger("presence.group_closing_llm")

_CLOSE_TOKEN = re.compile(r"\[\s*CLOSE\s*\]", re.IGNORECASE)
_KEEP_TOKEN = re.compile(r"\[\s*KEEP\s*\]", re.IGNORECASE)

_SYSTEM_PROMPT = (
    "Eres Lumi en un grupo de WhatsApp. Acabas de tener una conversación con "
    "alguien y ahora llega un mensaje nuevo. Decide si ese mensaje cierra la "
    "conversación contigo o no.\n\n"
    "REGLAS:\n"
    "- Si es un cierre claro (agradecimiento, despedida, confirmación final "
    "tipo 'gracias Lumi', 'listo Lumi', 'chao Lumi', 'ok perfecto Lumi'), "
    "responde con 1 a 5 palabras naturales y termina tu respuesta con el "
    "token literal [CLOSE].\n"
    "- Si el mensaje continúa el tema, hace una nueva pregunta, o introduce "
    "algo relacionado, responde SÓLO con el token literal [KEEP] (sin nada "
    "más).\n"
    "- Si tienes dudas, prefiere [KEEP].\n\n"
    "Ejemplos:\n"
    "Mensaje: 'gracias Lumi' → 'con gusto [CLOSE]'\n"
    "Mensaje: 'listo Lumi, y qué tal el otro juego?' → '[KEEP]'\n"
    "Mensaje: 'ok Lumi perfecto' → 'cuando quieras [CLOSE]'\n"
)


async def confirm_closing(
    user_msg: str,
    recent_history: list[dict] | None = None,
) -> tuple[bool, str | None]:
    """Retorna (is_close, short_reply).

    Si is_close=True, short_reply contiene la respuesta breve a enviar al grupo
    (sin el token [CLOSE]). Si is_close=False, short_reply es None y el caller
    debe re-enrutar al LLM principal.
    """
    context_lines = []
    for turn in (recent_history or [])[-4:]:
        role = "Lumi" if turn["role"] == "assistant" else "Usuario"
        context_lines.append(f"{role}: {turn['content']}")
    context_block = "\n".join(context_lines)

    user_content = (
        (f"Contexto reciente:\n{context_block}\n\n" if context_block else "")
        + f"Mensaje nuevo: {user_msg}"
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        resp = await chat(
            messages=messages,
            model_group=ModelGroup.LIGHTWEIGHT,
            max_tokens=40,
            temperature=0.3,
        )
    except Exception as e:
        logger.warning(f"[group_closing_llm] LLM call failed ({e}); defaulting to KEEP")
        return False, None

    content = (resp.get("content") or "").strip()
    logger.info(f"[group_closing_llm] raw_response={content!r}")

    if _CLOSE_TOKEN.search(content):
        short_reply = _CLOSE_TOKEN.sub("", content).strip()
        if not short_reply:
            short_reply = "con gusto"
        return True, short_reply

    # KEEP (explicit o por default si el modelo divagó)
    return False, None
