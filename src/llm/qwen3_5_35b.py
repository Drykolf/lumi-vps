import os
import logging
from openai import AsyncOpenAI, RateLimitError
from src.llm.base import BaseLLM

logger = logging.getLogger("llm.qwen3_5_35b")


class Qwen3_5_35B(BaseLLM):

    MODEL_ID = "Qwen/Qwen3.5-35B-A3B"

    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=os.getenv("DEEPINFRA_API_KEY"),
            base_url="https://api.deepinfra.com/v1/openai",
        )

    @property
    def model(self) -> str:
        return self.MODEL_ID

    def _kwargs(self, messages, tool_schemas, max_tokens, thinking, stream) -> dict:
        kwargs = dict(
            model=self.MODEL_ID,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            top_p=0.8,
            presence_penalty=1.5,
            stream=stream,
            extra_body={"top_k": 20, "chat_template_kwargs": {"enable_thinking": thinking}},
        )
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def chat(self, messages, tool_schemas=None, max_tokens=512, thinking=False) -> dict:
        response = await self._client.chat.completions.create(
            **self._kwargs(messages, tool_schemas, max_tokens, thinking, stream=False)
        )
        usage = response.usage
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
        logger.info(f"tokens — prompt: {usage.prompt_tokens} | cached: {cached} | completion: {usage.completion_tokens}")
        msg = response.choices[0].message
        return {"role": msg.role, "content": msg.content or "", "tool_calls": msg.tool_calls or []}

    async def chat_stream(self, messages, tool_schemas=None, thinking=False):
        stream = await self._client.chat.completions.create(
            **self._kwargs(messages, tool_schemas, 512, thinking, stream=True)
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta