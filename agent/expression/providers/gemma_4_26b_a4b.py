import os
import logging
from openai import AsyncOpenAI
from agent.expression.providers.base import BaseLLM

logger = logging.getLogger("llm.gemma_4_26b_a4b")


class Gemma4_26B_A4B(BaseLLM):

    MODEL_ID = "google/gemma-4-26B-A4B-it"

    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=os.getenv("DEEPINFRA_API_KEY"),
            base_url="https://api.deepinfra.com/v1/openai",
        )

    @property
    def model(self) -> str:
        return self.MODEL_ID

    def _kwargs(self, messages, tool_schemas, max_tokens, stream, temperature, reasoning_effort, prompt_cache_key=None) -> dict:
        enable_thinking = (reasoning_effort is not None and reasoning_effort != "none")
        extra_body = {"top_k": 20, "chat_template_kwargs": {"enable_thinking": enable_thinking}}
        if prompt_cache_key:
            extra_body["prompt_cache_key"] = prompt_cache_key
        kwargs = dict(
            model=self.MODEL_ID,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=0.8,
            presence_penalty=1.5,
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
        msg = response.choices[0].message
        return {"role": msg.role, "content": msg.content or "", "tool_calls": msg.tool_calls or []}

    async def chat_stream(self, messages, tool_schemas=None, temperature=0.7, reasoning_effort=None, prompt_cache_key=None):
        thinking = reasoning_effort is not None and reasoning_effort != "none"
        max_tokens = 2048 if thinking else 512
        stream = await self._client.chat.completions.create(
            **self._kwargs(messages, tool_schemas, max_tokens, stream=True, temperature=temperature, reasoning_effort=reasoning_effort, prompt_cache_key=prompt_cache_key)
        )
        full_content = []
        full_reasoning = []
        first_logged = False
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if not first_logged:
                logger.info(f"[{self.MODEL_ID}] primer delta: {delta.model_dump(exclude_none=True)}")
                first_logged = True
            if delta.content:
                full_content.append(delta.content)
                yield delta.content
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                full_reasoning.append(rc)
        reasoning_text = "".join(full_reasoning)
        content_text = "".join(full_content)
        if reasoning_text:
            logger.info(f"[{self.MODEL_ID}] reasoning ({len(reasoning_text)} chars): {reasoning_text[:300]}")
        if content_text:
            logger.info(f"[{self.MODEL_ID}] content ({len(content_text)} chars): {content_text[:300]}")
        else:
            logger.warning(f"[{self.MODEL_ID}] stream sin content — reasoning={len(reasoning_text)} chars, reasoning_effort={reasoning_effort}")
