import logging
from abc import ABC, abstractmethod

usage_logger = logging.getLogger("llm.usage")


class BaseLLM(ABC):

    @property
    @abstractmethod
    def model(self) -> str:
        pass

    def _log_usage(self, usage, *, stream: bool = False) -> None:
        """Loguea el consumo de tokens devuelto por la llamada al LLM."""
        if not usage:
            return
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        mode = "stream" if stream else "chat"
        usage_logger.info(
            f"[{self.model}] usage ({mode}) — prompt: {usage.prompt_tokens} | "
            f"cached: {cached} | completion: {usage.completion_tokens} | total: {usage.total_tokens}"
        )

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tool_schemas: list[dict] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        prompt_cache_key: str | None = None,
    ) -> dict:
        """
        Retorna dict con keys: role, content, tool_calls.
        """
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict],
        tool_schemas: list[dict] = None,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        prompt_cache_key: str | None = None,
    ):
        """
        Async generator que yield chunks de texto.
        """
        pass