import os
import logging
from openai import AsyncOpenAI
from agent.expression.providers.base import BaseLLM

logger = logging.getLogger("llm.deepseek")


class DeepSeek(BaseLLM):

    MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"

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
        )
        if not thinking:
            kwargs["extra_body"] = {"reasoning_effort": "none"}
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def chat(self, messages, tool_schemas=None, max_tokens=512, thinking=False) -> dict:
        response = await self._client.chat.completions.create(
            **self._kwargs(messages, tool_schemas, max_tokens, thinking, stream=False)
        )
        msg = response.choices[0].message
        return {"role": msg.role, "content": msg.content or "", "tool_calls": msg.tool_calls or []}

    async def chat_stream(self, messages, tool_schemas=None, thinking=False):
        stream = await self._client.chat.completions.create(
            **self._kwargs(messages, tool_schemas, 512, thinking, stream=True)
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
