"""
Factory LLM — orquestador con fallback automático.
loop.py importa este módulo directamente.
"""
import asyncio
import logging
import time
from enum import Enum
from openai import RateLimitError, APIStatusError
from agent.expression.providers.qwen3_5_35b import Qwen3_5_35B
from agent.expression.providers.qwen3_next_80b_a3b import Qwen3Next80B_A3B
from agent.expression.providers.gemma_4_26b_a4b import Gemma4_26B_A4B
from agent.expression.providers.mistral import Mistral
from agent.expression.providers.deepseek import DeepSeek
from agent.expression.providers.qwen_9b import Qwen9B

logger = logging.getLogger("llm")


class ModelGroup(Enum):
    MAIN = "main"
    LIGHTWEIGHT = "lightweight"


# ── Registries de modelos en orden de prioridad ───────────────────────────────
_MAIN_MODELS = [
    Gemma4_26B_A4B(),
    Qwen3_5_35B(),
    Qwen3Next80B_A3B(),
]

_LIGHTWEIGHT_MODELS = [
    Mistral(),
    DeepSeek(),
    Qwen9B(),
]

_MODEL_GROUPS = {
    ModelGroup.MAIN: _MAIN_MODELS,
    ModelGroup.LIGHTWEIGHT: _LIGHTWEIGHT_MODELS,
}


def _resolve_models(model_group: ModelGroup):
    try:
        return _MODEL_GROUPS[model_group]
    except KeyError:
        raise ValueError(f"Grupo de modelos desconocido: {model_group}")


async def _try_models(method: str, model_group: ModelGroup = ModelGroup.MAIN, **kwargs):
    for llm_instance in _resolve_models(model_group):
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
            except APIStatusError:
                logger.warning(f"{llm_instance.model} rechazo la solicitud (API error), probando siguiente...")
                break
        logger.warning(f"{llm_instance.model} agotado, probando siguiente...")
    raise RuntimeError("Todos los modelos están saturados.")


async def test_models(reasoning_effort="default") -> dict:
    """
    Prueba todos los modelos registrados con un mensaje simple.
    Retorna resultados agrupados por grupo (main/lightweight).
    """
    results: dict[str, dict] = {}
    test_messages = [{"role": "user", "content": "Hola, cuanto es 2 + 2? solo responder con el resultado"}]

    for group_name, models in _MODEL_GROUPS.items():
        group_results = {}
        for llm in models:
            model_name = llm.model
            start = time.monotonic()
            try:
                if reasoning_effort == "default":
                    response = await llm.chat(test_messages, max_tokens=20, temperature=0.1)
                else:
                    response = await llm.chat(test_messages, max_tokens=20, temperature=0.1, reasoning_effort=reasoning_effort)
                elapsed = time.monotonic() - start
                content = response.get("content", "")
                group_results[model_name] = {
                    "status": "ok",
                    "latency_ms": round(elapsed * 1000, 1),
                    "reasoning_effort": reasoning_effort,
                    "response": content[:100],
                }
                logger.info(f"[test_models] {model_name} OK ({elapsed*1000:.0f}ms): {content[:100]}")
            except Exception as e:
                elapsed = time.monotonic() - start
                group_results[model_name] = {
                    "status": "error",
                    "latency_ms": round(elapsed * 1000, 1),
                    "error": str(e),
                    "reasoning_effort": reasoning_effort,
                }
                logger.warning(f"[test_models] {model_name} FAIL ({elapsed*1000:.0f}ms): {e}")
        results[group_name.value] = group_results

    return results


async def chat(messages, tool_schemas=None, max_tokens=512,
               temperature: float = 0.7, reasoning_effort: str | None = None,
               model_group: ModelGroup = ModelGroup.MAIN,
               prompt_cache_key: str | None = None) -> dict:
    return await _try_models("chat", model_group=model_group, messages=messages,
                              tool_schemas=tool_schemas, max_tokens=max_tokens,
                              temperature=temperature,
                              reasoning_effort=reasoning_effort,
                              prompt_cache_key=prompt_cache_key)


async def chat_stream(messages, tool_schemas=None,
                      temperature: float = 0.7, reasoning_effort: str | None = None,
                      model_group: ModelGroup = ModelGroup.MAIN,
                      prompt_cache_key: str | None = None):
    # chat_stream es async generator — necesita manejo especial
    for llm_instance in _resolve_models(model_group):
        for attempt in range(2):
            try:
                async for chunk in llm_instance.chat_stream(messages, tool_schemas, temperature, reasoning_effort, prompt_cache_key):
                    yield chunk
                return
            except RateLimitError:
                wait = 2 ** attempt
                logger.warning(f"Rate limit en {llm_instance.model} (stream), reintentando en {wait}s...")
                await asyncio.sleep(wait)
            except APIStatusError:
                logger.warning(f"{llm_instance.model} rechazo la solicitud (API error, stream), probando siguiente...")
                break
        logger.warning(f"{llm_instance.model} agotado (stream), probando siguiente...")
    raise RuntimeError("Todos los modelos están saturados.")