import os
import logging
from openai import AsyncOpenAI
from agent.expression.providers.base import BaseLLM

logger = logging.getLogger("llm.nemotron_super_120b")


class NemotronSuper120B(BaseLLM):

    MODEL_ID = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B"

    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=os.getenv("DEEPINFRA_API_KEY"),
            base_url="https://api.deepinfra.com/v1/openai",
        )

    @property
    def model(self) -> str:
        return self.MODEL_ID

    def _kwargs(self, messages, tool_schemas, max_tokens, stream, temperature, reasoning_effort) -> dict:
        # Nemotron no usa chat_template_kwargs ni reasoning_effort
        kwargs = dict(
            model=self.MODEL_ID,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=0.8,
            presence_penalty=1.5,
            stream=stream,
        )
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def chat(self, messages, tool_schemas=None, max_tokens=512, temperature=0.7, reasoning_effort=None) -> dict:
        response = await self._client.chat.completions.create(
            **self._kwargs(messages, tool_schemas, max_tokens, stream=False, temperature=temperature, reasoning_effort=reasoning_effort)
        )
        msg = response.choices[0].message
        return {"role": msg.role, "content": msg.content or "", "tool_calls": msg.tool_calls or []}

    async def chat_stream(self, messages, tool_schemas=None, temperature=0.7, reasoning_effort=None):
        stream = await self._client.chat.completions.create(
            **self._kwargs(messages, tool_schemas, 512, stream=True, temperature=temperature, reasoning_effort=reasoning_effort)
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content