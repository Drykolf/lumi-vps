import os
import httpx
import logging
from src.tools.base import BaseTool

logger = logging.getLogger("brave_search")

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchTool(BaseTool):

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Busca información actual en la web. Usar cuando el usuario pregunta por noticias, precios, eventos recientes o cualquier dato que pueda haber cambiado."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "El término o pregunta a buscar en la web."
                }
            },
            "required": ["query"]
        }

    async def run(self, query: str, count: int = 5) -> dict:
        api_key = os.getenv("BRAVE_API_KEY")
        if not api_key:
            return {"error": "BRAVE_API_KEY no configurada"}

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                BRAVE_URL,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
                params={"q": query, "count": count},
            )
            resp.raise_for_status()

        data = resp.json()
        results = data.get("web", {}).get("results", [])
        return {
            "results": [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "description": r.get("description", ""),
                }
                for r in results
            ]
        }