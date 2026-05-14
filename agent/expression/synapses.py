"""
Factory LLM — orquestador con fallback automático.
loop.py importa este módulo directamente.
"""
import asyncio
import logging
from enum import Enum
from openai import RateLimitError, APIStatusError
from agent.expression.providers.qwen3_5_35b import Qwen3_5_35B
from agent.expression.providers.step_3_5_flash import Step3_5Flash
from agent.expression.providers.nemotron_super_120b import NemotronSuper120B
from agent.expression.providers.mistral import Mistral
from agent.expression.providers.deepseek import DeepSeek
from agent.expression.providers.qwen_9b import Qwen9B

logger = logging.getLogger("llm")


class ModelGroup(Enum):
    MAIN = "main"
    LIGHTWEIGHT = "lightweight"


# ── Registries de modelos en orden de prioridad ───────────────────────────────
_MAIN_MODELS = [
    Qwen3_5_35B(),
    Step3_5Flash(),
    NemotronSuper120B(),
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


async def chat(messages, tool_schemas=None, max_tokens=512, thinking=False,
               temperature: float = 0.7, reasoning_effort: str | None = None,
               model_group: ModelGroup = ModelGroup.MAIN) -> dict:
    return await _try_models("chat", model_group=model_group, messages=messages,
                              tool_schemas=tool_schemas, max_tokens=max_tokens,
                              thinking=thinking, temperature=temperature,
                              reasoning_effort=reasoning_effort)


async def chat_stream(messages, tool_schemas=None, thinking=False,
                      temperature: float = 0.7, reasoning_effort: str | None = None,
                      model_group: ModelGroup = ModelGroup.MAIN):
    # chat_stream es async generator — necesita manejo especial
    for llm_instance in _resolve_models(model_group):
        for attempt in range(2):
            try:
                async for chunk in llm_instance.chat_stream(messages, tool_schemas, thinking, temperature, reasoning_effort):
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