from abc import ABC, abstractmethod


class BaseTool(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    def parameters(self) -> dict:
        """Schema de parámetros OpenAI-compatible. Override si la tool tiene args."""
        return {"type": "object", "properties": {}, "required": []}

    @abstractmethod
    async def run(self, **kwargs) -> dict:
        pass

    def schema(self) -> dict:
        """Schema completo para el LLM. No override salvo caso especial."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }