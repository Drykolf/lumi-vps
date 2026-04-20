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
        thinking: bool = False,
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
        thinking: bool = False,
    ):
        """
        Async generator que yield chunks de texto.
        """
        pass