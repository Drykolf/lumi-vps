import asyncio
import logging
import os

from openai import AsyncOpenAI, RateLimitError
from src.llm.base import BaseLLM

logger = logging.getLogger("llm.deepinfra")

_PRIMARY = "Qwen/Qwen3.5-35B-A3B"
_FALLBACKS = [
    "stepfun-ai/Step-3.5-Flash",
    "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B",
]

# Modelos que NO soportan chat_template_kwargs — usan su propio extra_body
_MODEL_EXTRA_BODY: dict[str, dict] = {
    "stepfun-ai/Step-3.5-Flash": {"reasoning_effort": "none"},
    "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B": {},
}


def _extra_body(model: str, thinking: bool) -> dict:
    if model in _MODEL_EXTRA_BODY:
        return _MODEL_EXTRA_BODY[model]
    return {"top_k": 20, "chat_template_kwargs": {"enable_thinking": thinking}}


class DeepInfraLLM(BaseLLM):

    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=os.getenv("DEEPINFRA_API_KEY"),
            base_url="https://api.deepinfra.com/v1/openai",
        )

    @property
    def model(self) -> str:
        return _PRIMARY

    def _build_kwargs(self, model: str, messages: list, tool_schemas: list,
                      max_tokens: int, thinking: bool, stream: bool) -> dict:
        kwargs = dict(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            top_p=0.8,
            presence_penalty=1.5,
            stream=stream,
            extra_body=_extra_body(model, thinking),
        )
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def _try_models(self, stream: bool, **kwargs_base):
        for model in [_PRIMARY] + _FALLBACKS:
            for attempt in range(2):
                try:
                    kwargs = self._build_kwargs(model=model, stream=stream, **kwargs_base)
                    response = await self._client.chat.completions.create(**kwargs)
                    if model != _PRIMARY:
                        logger.warning(f"Usando fallback: {model}")
                    return response
                except RateLimitError:
                    wait = 2 ** attempt
                    logger.warning(f"Rate limit en {model}, reintentando en {wait}s...")
                    await asyncio.sleep(wait)
            logger.warning(f"{model} agotado, probando siguiente...")
        raise RuntimeError("Todos los modelos están saturados.")

    async def chat(self, messages, tool_schemas=None, max_tokens=512, thinking=False) -> dict:
        response = await self._try_models(
            stream=False,
            messages=messages,
            tool_schemas=tool_schemas,
            max_tokens=max_tokens,
            thinking=thinking,
        )
        usage = response.usage
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
        logger.info(f"tokens — prompt: {usage.prompt_tokens} | cached: {cached} | completion: {usage.completion_tokens}")
        msg = response.choices[0].message
        return {
            "role": msg.role,
            "content": msg.content or "",
            "tool_calls": msg.tool_calls or [],
        }

    async def chat_stream(self, messages, tool_schemas=None, thinking=False):
        stream = await self._try_models(
            stream=True,
            messages=messages,
            tool_schemas=tool_schemas,
            max_tokens=512,
            thinking=thinking,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta