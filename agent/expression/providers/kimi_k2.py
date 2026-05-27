import os
import logging
from openai import AsyncOpenAI
from agent.expression.providers.base import BaseLLM

logger = logging.getLogger("llm.kimi_k2")


class KimiK2(BaseLLM):

    MODEL_ID = "moonshotai/Kimi-K2.6"

    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=os.getenv("DEEPINFRA_API_KEY"),
            base_url="https://api.deepinfra.com/v1/openai",
        )

    @property
    def model(self) -> str:
        return self.MODEL_ID

    def _kwargs(self, messages, tool_schemas, max_tokens, stream, temperature, reasoning_effort, prompt_cache_key=None) -> dict:
        extra_body = {}
        if prompt_cache_key:
            extra_body["prompt_cache_key"] = prompt_cache_key
        kwargs = dict(
            model=self.MODEL_ID,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
        )
        # Always send reasoning_effort — Kimi K2.6 thinks by default if the kwarg is absent.
        kwargs["reasoning_effort"] = reasoning_effort if (reasoning_effort and reasoning_effort != "none") else "none"
        if extra_body:
            kwargs["extra_body"] = extra_body
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def chat(self, messages, tool_schemas=None, max_tokens=1024, temperature=0.7, reasoning_effort=None, prompt_cache_key=None) -> dict:
        response = await self._client.chat.completions.create(
            **self._kwargs(messages, tool_schemas, max_tokens, stream=False, temperature=temperature, reasoning_effort=reasoning_effort, prompt_cache_key=prompt_cache_key)
        )
        usage = response.usage
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
        logger.info(f"tokens — prompt: {usage.prompt_tokens} | cached: {cached} | completion: {usage.completion_tokens}")
        msg = response.choices[0].message
        content = msg.content or getattr(msg, "reasoning_content", None) or ""
        if not msg.content and content:
            logger.warning(f"[{self.MODEL_ID}] content vacío — usando reasoning_content como fallback ({len(content)} chars)")
        return {"role": msg.role, "content": content, "tool_calls": msg.tool_calls or []}

    async def chat_stream(self, messages, tool_schemas=None, temperature=0.7, reasoning_effort=None, prompt_cache_key=None):
        thinking = reasoning_effort is not None and reasoning_effort != "none"
        max_tokens = 4096 if thinking else 1024
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
        elif reasoning_text:
            # Kimi produced only reasoning with no final content — surface the reasoning so callers
            # get something rather than silence. Logged as warning so this remains visible.
            logger.warning(f"[{self.MODEL_ID}] stream sin content — usando reasoning como fallback ({len(reasoning_text)} chars)")
            yield reasoning_text
        else:
            logger.warning(f"[{self.MODEL_ID}] stream sin content ni reasoning — reasoning_effort={reasoning_effort}")
