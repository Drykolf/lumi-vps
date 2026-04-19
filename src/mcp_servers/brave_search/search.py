import os
import httpx
import logging

logger = logging.getLogger("brave_search")

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


async def search(query: str, count: int = 5) -> list[dict]:
    """
    Busca en la web via Brave Search API.
    Retorna lista de {title, url, description}.
    """
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        return [{"error": "BRAVE_API_KEY no configurada"}]

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

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("description", ""),
        }
        for r in results
    ]