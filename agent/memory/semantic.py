"""
Cliente de memoria — Fase 4: Mem0 + pgvector.
Operaciones de memoria semantica via Mem0 REST API.

SQLite operations (historial, sesiones, resumenes) estan en sqlite_memory.py.
"""
import httpx
import os

from agent.substrate.logger import get_logger

logger = get_logger("mem0_client")

# ── Config ────────────────────────────────────────────────────────────────────
MEM0_URL = os.getenv("MEM0_URL", "http://localhost:8100")
MEM0_API_KEY = os.getenv("MEM0_ADMIN_API_KEY", "")
TIMEOUT = 10


# ── Mem0 — memoria semantica ──────────────────────────────────────────────────

def _headers() -> dict:
    return {"Content-Type": "application/json", "X-API-Key": MEM0_API_KEY}


async def add_memory(messages: list[dict], user_id: str) -> list[dict]:
    """
    Envía la conversación a Mem0 para extracción de hechos.
    Se llama al cierre de cada turno o sesión.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{MEM0_URL}/memories",
                headers=_headers(),
                json={"messages": messages, "user_id": user_id},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                facts = [r.get("memory", "") for r in results]
                logger.info(f"add_memory: extracted {facts}")
            return results
    except Exception as e:
        logger.warning(f"mem0 add_memory failed: {e}")
        return []


async def search_relevant(user_id: str, query: str, limit: int = 5) -> list[str]:
    """
    Búsqueda semántica en Mem0. Reemplaza el placeholder de Fase 3.
    Retorna lista de strings con los hechos más relevantes.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{MEM0_URL}/search",
                headers=_headers(),
                json={
                    "query": query,
                    "filters": {"user_id": user_id},
                    "top_k": limit,
                },
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            logger.info(f"search_relevant: query='{query[:80]}' → {len(results)} results{', scores: '+str([round(r.get('score',0),3) for r in results]) if results else ''}")
            #logger.info(f"search_relevant: results={results}")
            return [r["memory"] for r in results if r.get("memory")]
    except Exception as e:
        logger.warning(f"mem0 search_relevant failed: {e}")
        return []


async def save_explicit(content: str, user_id: str, category: str = "note") -> dict:
    """
    Guarda contenido verbatim sin pasar por el extractor LLM.
    Para recetas, links, notas, codigo, referencias explicitas.
    Retorna dict con success + memory text para verificacion por el caller.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{MEM0_URL}/memories",
                headers=_headers(),
                json={
                    "messages": [{"role": "user", "content": content}],
                    "user_id": user_id,
                    "infer": False,
                    "metadata": {"category": category},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            memory_text = results[0].get("memory", content) if results else content
            logger.info(f"save_explicit: saved memory for user {user_id}")
            return {"success": True, "memory": memory_text, "category": category}
    except Exception as e:
        logger.warning(f"mem0 save_explicit failed: {e}")
        return {"success": False, "error": str(e)}