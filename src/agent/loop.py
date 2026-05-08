"""
Orquestador principal — sección 2.2 y loop del manual.
Ciclo: clasificar → contexto → LLM → tools → memoria → retornar.
"""
import json
import logging
import re

from src.agent import router, tools, llm
from src.agent.context import build_messages
from src.agent.memory import save_turn, init_db, init_core_db, add_memory_explicit
from src.state.internal_state import init_state_table

logger = logging.getLogger("agent.loop")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)

MAX_ITERATIONS = 10

# Inicializar tablas al importar
init_db()
init_core_db()
init_state_table()
logger.info("loop module initialized — explicit_save logging active")

_CATEGORY_NAMES = {
    "recipe": "receta", "link": "enlace", "note": "nota",
    "code": "codigo", "reference": "referencia",
}

_PROMPT_PROCESS_EXPLICIT = """Reestructura el siguiente mensaje en una memoria para Mem0.
Reglas:
- Español, tercera persona, conciso y factual.
- Empieza con "guardó" o "anotó" según corresponda.
- Si es receta: incluye nombre, ingredientes y preparación en un solo párrafo.
- Si es link: "guardó un enlace: [URL] - [descripción]".
- Si es nota: "anotó: [contenido]".
- Si es código: "guardó un código de [lenguaje]: [descripción]. [código]".
- Si es referencia: "guardó una referencia de [fuente]: [descripción]".
- ELIMINA frases como "necesito que guardes", "por favor", "para cuando pregunte", etc.
- NO incluyas nombre del usuario.
- NO inventes información que no esté en el mensaje.

Responde SOLO con un JSON en una línea:
{"category": "recipe|link|note|code|reference", "memory": "texto de la memoria"}"""


async def _process_explicit_memory(message: str) -> dict:
    """Reestructura un mensaje de guardado explícito en formato de memoria limpio usando LLM."""
    logger.info(f"[explicit_save] processing memory via LLM | message_len={len(message)}")
    try:
        response = await llm.chat(
            messages=[
                {"role": "system", "content": _PROMPT_PROCESS_EXPLICIT},
                {"role": "user", "content": message},
            ],
            max_tokens=300,
        )
        content = response.get("content", "").strip()
        logger.info(f"[explicit_save] LLM raw response | len={len(content)} | preview={content[:100]}")
        match = re.search(
            r'\{.*"category"\s*:\s*"(recipe|link|note|code|reference)"\s*,\s*"memory"\s*:\s*".*"\s*\}',
            content, re.DOTALL,
        )
        if match:
            parsed = json.loads(match.group(0))
            logger.info(f"[explicit_save] parsed memory | category={parsed['category']} | mem_len={len(parsed['memory'])}")
            return parsed
        logger.warning(f"[explicit_save] JSON regex did not match LLM response")
    except Exception as e:
        logger.exception(f"[explicit_save] _process_explicit_memory failed: {e}")
    logger.info(f"[explicit_save] falling back to raw message as memory")
    return {"category": "note", "memory": message}


def _inject_save_verification(messages: list[dict], result: dict, category: str):
    """Prepend save verification to the system prompt so Lumi responds dynamically."""
    cat_name = _CATEGORY_NAMES.get(category, category)
    if result.get("success"):
        saved = result.get("memory", "")[:300]
        msg = (
            f"[Sistema interno: El mensaje del usuario fue guardado en Mem0 "
            f"como {cat_name}. Contenido: {saved}. "
            f"Confirma el guardado de forma natural, en tu voz.]"
        )
    else:
        msg = (
            "[Sistema interno: El intento de guardar en Mem0 fallo. "
            "El servicio de memoria no esta disponible. "
            "Informa al usuario con honestidad, sin alarmismo.]"
        )
    messages[0]["content"] = msg + "\n\n" + messages[0]["content"]

async def run_stream(user_id: str, message: str, metadata: dict):
    task_type = router.classify(message)
    logger.info(f"[classify] task_type={task_type} | msg_preview={message[:80]}")

    if task_type == "long_task":
        save_turn(user_id, "user", message)
        reply = "[thinking] Dame un momento, esto toma un poco más de tiempo."
        save_turn(user_id, "assistant", reply)
        yield reply
        return

    if task_type == "explicit_save":
        category = router.detect_category(message)
        logger.info(f"[explicit_save] category={category} | user_id={user_id}")
        processed = await _process_explicit_memory(message)
        result = await add_memory_explicit(processed["memory"], user_id, processed.get("category", category))
        save_turn(user_id, "user", message)
        logger.info(f"[explicit_save] saved to Mem0 | success={result.get('success')} | category={result.get('category')}")
        messages = await build_messages(user_id, message, metadata)
        _inject_save_verification(messages, result, processed.get("category", category))

        response_msg = await llm.chat(messages)
        reply_text = response_msg.get("content", "")
        if not reply_text:
            cat_name = _CATEGORY_NAMES.get(processed.get("category", category), "eso")
            reply_text = f"[neutral] Listo, guarde {cat_name} en mi memoria."
        yield reply_text

        save_turn(user_id, "assistant", reply_text)
        logger.info(f"[explicit_save] stream response | reply_len={len(reply_text)} | preview={reply_text[:80]}")
        return

    messages = await build_messages(user_id, message, metadata)
    schemas = tools.all_schemas()

    # ── Loop tool calls (no streaming hasta tener respuesta final) ────────────
    for iteration in range(MAX_ITERATIONS):
        response_msg = await llm.chat(messages, tool_schemas=schemas or None)

        if tools.has_tool_calls(response_msg):
            raw_calls = response_msg.get("tool_calls") or []
            tool_calls = [
                {
                    "function": {
                        "name": tc.function.name if hasattr(tc, "function") else tc.get("function", {}).get("name"),
                        "arguments": tc.function.arguments if hasattr(tc, "function") else tc.get("function", {}).get("arguments", {}),
                    }
                }
                for tc in raw_calls
            ]
            tool_results = await tools.execute(tool_calls, user_id)
            # response_msg es un dict con tool_calls como objetos del SDK
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    }
                    for tc in response_msg.get("tool_calls", [])
                ]
            })

            for tc, result in zip(response_msg.get("tool_calls", []), tool_results):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result.get("result", "")),
                })
            continue

        # Respuesta final — ahora sí streamear
        break

    full_reply = ""
    async for chunk in llm.chat_stream(messages):
        full_reply += chunk
        yield chunk

    save_turn(user_id, "user", message)
    save_turn(user_id, "assistant", full_reply)
    
async def run(user_id: str, message: str, metadata: dict) -> str:
    """
    Punto de entrada del agente.
    metadata: dict con channel, session_id, source, was_interruption, etc.
    """

    # ── 1. Clasificación pre-LLM ─────────────────────────────────────────────
    task_type = router.classify(message)
    logger.info(f"[classify] task_type={task_type} | msg_preview={message[:80]}")

    if task_type == "long_task":
        # Fase 3: respuesta inmediata, async real llega en Fase 4
        save_turn(user_id, "user", message)
        reply = "[thinking] Dame un momento, esto toma un poco más de tiempo."
        save_turn(user_id, "assistant", reply)
        return reply

    if task_type == "web_search":
        # Fase 3: aviso de que search no está activo aún
        # Fase 4: Brave Search se inyecta en el contexto aquí
        metadata["web_search_needed"] = True

    if task_type == "explicit_save":
        category = router.detect_category(message)
        logger.info(f"[explicit_save] category={category} | message_len={len(message)} | user_id={user_id}")
        processed = await _process_explicit_memory(message)
        result = await add_memory_explicit(processed["memory"], user_id, processed.get("category", category))
        logger.info(f"[explicit_save] save result={result}")
        save_turn(user_id, "user", message)

        messages = await build_messages(user_id, message, metadata)
        _inject_save_verification(messages, result, processed.get("category", category))

        response_msg = await llm.chat(messages)
        reply_text = response_msg.get("content", "")
        save_turn(user_id, "assistant", reply_text)
        return reply_text
        
    # ── 2. Construir contexto ────────────────────────────────────────────────
    messages = await build_messages(user_id, message, metadata)

    # ── 3. Loop LLM + tools ──────────────────────────────────────────────────
    reply_text = ""

    for iteration in range(MAX_ITERATIONS):
        response_msg = await llm.chat(messages)
        reply_text = response_msg.get("content", "")

        # Tool calls
        if tools.has_tool_calls(response_msg):
            logger.info(f"tool_calls detectados: {response_msg.get('tool_calls')}") 
            raw_calls = response_msg.get("tool_calls") or []
            tool_calls = [
                {
                    "function": {
                        "name": tc.function.name if hasattr(tc, "function") else tc.get("function", {}).get("name"),
                        "arguments": tc.function.arguments if hasattr(tc, "function") else tc.get("function", {}).get("arguments", {}),
                    }
                }
                for tc in raw_calls
            ]
            tool_results = await tools.execute(tool_calls, user_id)
            messages.append(response_msg)
            messages.append({
                "role": "tool",
                "content": str(tool_results)
            })
            continue

        # Escalamiento a modelo especialista
        if "[ESCALAR]" in reply_text:
            # Fase 4+: llamar a modelo especializado
            reply_text = reply_text.replace("[ESCALAR]", "").strip()

        # Seguimiento asociativo (encolar, no bloquear)
        if "[SEGUIMIENTO:" in reply_text:
            # Fase 5+: followup_queue.enqueue()
            pass

        break  # respuesta final obtenida

    else:
        reply_text = "[neutral] No logré resolver esto en el tiempo esperado."

    # ── 4. Guardar en memoria ────────────────────────────────────────────────
    save_turn(user_id, "user", message)
    save_turn(user_id, "assistant", reply_text)

    return reply_text
