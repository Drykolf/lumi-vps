"""
Cliente de memoria — Fase 4: Mem0 + pgvector.
Operaciones de memoria semantica via Mem0 REST API.

SQLite operations (historial, sesiones, resumenes) estan en sqlite_memory.py.
"""
import httpx
import logging
import os

logger = logging.getLogger("mem0_client")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)

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
            return resp.json().get("results", [])
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
                json={"query": query, "filters": {"user_id": user_id}, "top_k": limit},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            return [r["memory"] for r in results if r.get("memory")]
    except Exception as e:
        logger.warning(f"mem0 search_relevant failed: {e}")
        return []


async def get_profile(user_id: str) -> dict | None:
    """
    Retorna el perfil del usuario desde Mem0.
    Fase 4 placeholder: busca memorias tipo user_profile.
    TODO: estructurar como JSON persistente en Fase 4 completo.
    """
    memories = await search_relevant(user_id, f"perfil usuario {user_id}", limit=10)
    if not memories:
        return None
    return {"user_id": user_id, "memories": memories}


async def set_profile(user_id: str, display_name: str, description: str = "", metadata: dict = None) -> dict:
    """
    Guarda datos de perfil en Mem0 como memorias.
    TODO Fase 4: reemplazar por user_profile JSON estructurado.
    """
    messages = [{"role": "user", "content": f"Mi nombre es {display_name}. {description}"}]
    await add_memory(messages, user_id)
    return {"user_id": user_id, "display_name": display_name}


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
                    "infer": False,  # desactiva el extractor
                    "metadata": {"category": category}
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            memory_text = results[0].get("memory", content) if results else content
            return {"success": True, "memory": memory_text, "category": category}
    except Exception as e:
        logger.warning(f"mem0 save_explicit failed: {e}")
        return {"success": False, "error": str(e)}