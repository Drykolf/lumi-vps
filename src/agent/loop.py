"""
Orquestador principal — sección 2.2 y loop del manual.
Ciclo: clasificar → contexto → LLM → tools → memoria → retornar.
"""
from src.agent import router, tools, llm
from src.agent.context import build_messages
from src.agent.memory import save_turn, init_db
from src.state.internal_state import init_state_table

MAX_ITERATIONS = 10

# Inicializar tablas al importar
init_db()
init_state_table()

async def run_stream(user_id: str, message: str, metadata: dict):
    task_type = router.classify(message)

    if task_type == "long_task":
        save_turn(user_id, "user", message)
        reply = "[thinking] Dame un momento, esto toma un poco más de tiempo."
        save_turn(user_id, "assistant", reply)
        yield reply
        return

    messages = build_messages(user_id, message, metadata)

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

    # ── 2. Construir contexto ────────────────────────────────────────────────
    messages = build_messages(user_id, message, metadata)

    # ── 3. Loop LLM + tools ──────────────────────────────────────────────────
    reply_text = ""

    for iteration in range(MAX_ITERATIONS):
        response_msg = await llm.chat(messages)
        reply_text = response_msg.get("content", "")

        # Tool calls
        if tools.has_tool_calls(response_msg):
            tool_results = await tools.execute(response_msg["tool_calls"], user_id)
            messages.append(response_msg)
            messages.append({
                "role": "tool",
                "content": str(tool_results)
            })
            continue  # siguiente iteración con resultados

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
