"""
Message type handlers — dispatched by the orchestrator.
Each handler takes a classified message and returns the reply.
"""
from src.agent import router
from src.llm.factory import chat
from src.agent.context import build_messages
from src.memory.facade import add_memory_explicit, process_explicit_memory
from src.utils.logger import get_logger

logger = get_logger("agent.handlers")

_CATEGORY_NAMES = {
    "recipe": "receta", "link": "enlace", "note": "nota",
    "code": "codigo", "reference": "referencia",
}


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


async def handle_long_task(user_id: str, message: str, sid: str) -> str:
    return "[thinking] Dame un momento, esto toma un poco mas de tiempo."


async def handle_explicit_save(user_id: str, message: str, sid: str, metadata: dict) -> str:
    category = router.detect_category(message)
    logger.info(f"[explicit_save] category={category} | user_id={user_id}")
    processed = await process_explicit_memory(message)
    result = await add_memory_explicit(processed["memory"], user_id, processed.get("category", category))
    logger.info(f"[explicit_save] saved to Mem0 | success={result.get('success')} | category={result.get('category')}")
    messages = await build_messages(user_id, message, metadata)
    _inject_save_verification(messages, result, processed.get("category", category))
    response_msg = await chat(messages)
    reply_text = response_msg.get("content", "")
    if not reply_text:
        cat_name = _CATEGORY_NAMES.get(processed.get("category", category), "eso")
        reply_text = f"[neutral] Listo, guarde {cat_name} en mi memoria."
    logger.info(f"[explicit_save] response | reply_len={len(reply_text)} | preview={reply_text[:80]}")
    return reply_text


def handle_web_search(metadata: dict):
    metadata["web_search_needed"] = True
