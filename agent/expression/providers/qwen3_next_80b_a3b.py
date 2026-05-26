import os
import logging
from openai import AsyncOpenAI
from agent.expression.providers.base import BaseLLM

logger = logging.getLogger("llm.qwen3_next_80b_a3b")


class Qwen3Next80B_A3B(BaseLLM):

    MODEL_ID = "Qwen/Qwen3-Next-80B-A3B-Instruct"

    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=os.getenv("DEEPINFRA_API_KEY"),
            base_url="https://api.deepinfra.com/v1/openai",
        )

    @property
    def model(self) -> str:
        return self.MODEL_ID

    def _kwargs(self, messages, tool_schemas, max_tokens, stream, temperature, reasoning_effort, prompt_cache_key=None) -> dict:
        # Qwen3-Next-Instruct no razona — ignora reasoning_effort. Tampoco soporta prompt_cache_key.
        extra_body = {"top_k": 20}
        kwargs = dict(
            model=self.MODEL_ID,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=0.8,
            presence_penalty=1.0,
            stream=stream,
            extra_body=extra_body,
        )
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def chat(self, messages, tool_schemas=None, max_tokens=512, temperature=0.7, reasoning_effort=None, prompt_cache_key=None) -> dict:
        response = await self._client.chat.completions.create(
            **self._kwargs(messages, tool_schemas, max_tokens, stream=False, temperature=temperature, reasoning_effort=reasoning_effort, prompt_cache_key=prompt_cache_key)
        )
        usage = response.usage
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
        logger.info(f"tokens — prompt: {usage.prompt_tokens} | cached: {cached} | completion: {usage.completion_tokens}")
        msg = response.choices[0].message
        return {"role": msg.role, "content": msg.content or "", "tool_calls": msg.tool_calls or []}

    async def chat_stream(self, messages, tool_schemas=None, temperature=0.7, reasoning_effort=None, prompt_cache_key=None):
        stream = await self._client.chat.completions.create(
            **self._kwargs(messages, tool_schemas, 512, stream=True, temperature=temperature, reasoning_effort=reasoning_effort, prompt_cache_key=prompt_cache_key)
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
