from abc import ABC, abstractmethod


class BaseLLM(ABC):

    @property
    @abstractmethod
    def model(self) -> str:
        pass

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tool_schemas: list[dict] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
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
    ):
        """
        Async generator que yield chunks de texto.
        """
        pass