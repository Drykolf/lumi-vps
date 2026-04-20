"""
Factory LLM — orquestador con fallback automático.
loop.py importa este módulo directamente.
"""
import asyncio
import logging
from openai import RateLimitError
from src.llm.qwen3_5_35b import Qwen3_5_35B
from src.llm.step_3_5_flash import Step3_5Flash
from src.llm.nemotron_super_120b import NemotronSuper120B

logger = logging.getLogger("llm")

# ── Registry de modelos en orden de prioridad ─────────────────────────────────
_MODELS = [
    Qwen3_5_35B(),
    Step3_5Flash(),
    NemotronSuper120B(),
]


async def _try_models(method: str, **kwargs):
    for llm_instance in _MODELS:
        for attempt in range(2):
            try:
                result = getattr(llm_instance, method)(**kwargs)
                # Si es coroutine (chat), awaitar
                if hasattr(result, "__await__"):
                    return await result
                # Si es async generator (chat_stream), retornar directamente
                return result
            except RateLimitError:
                wait = 2 ** attempt
                logger.warning(f"Rate limit en {llm_instance.model}, reintentando en {wait}s...")
                await asyncio.sleep(wait)
        logger.warning(f"{llm_instance.model} agotado, probando siguiente...")
    raise RuntimeError("Todos los modelos están saturados.")


async def chat(messages, tool_schemas=None, max_tokens=512, thinking=False) -> dict:
    return await _try_models("chat", messages=messages, tool_schemas=tool_schemas,
                              max_tokens=max_tokens, thinking=thinking)


async def chat_stream(messages, tool_schemas=None, thinking=False):
    # chat_stream es async generator — necesita manejo especial
    for llm_instance in _MODELS:
        for attempt in range(2):
            try:
                async for chunk in llm_instance.chat_stream(messages, tool_schemas, thinking):
                    yield chunk
                return
            except RateLimitError:
                wait = 2 ** attempt
                logger.warning(f"Rate limit en {llm_instance.model} (stream), reintentando en {wait}s...")
                await asyncio.sleep(wait)
        logger.warning(f"{llm_instance.model} agotado (stream), probando siguiente...")
    raise RuntimeError("Todos los modelos están saturados.")