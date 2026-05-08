"""
Cliente de memoria — Fase 4: Mem0 + pgvector.
Reemplaza sqlite_memory.py manteniendo interfaz pública idéntica.

Pendientes Fase 4+:
- add_lumi_memory() / search_lumi_memory() — memorias de Lumi sobre sí misma (agent_id="lumi")
- save_session_summary() — resumen al cierre de sesión + limpiar history.db
- save_future_event() — eventos futuros con metadata de fecha
- save_relational_memory() — personas con metadata entity_type/entity_name
- get_lumi_state() / update_lumi_state() — internal_state de Lumi en Mem0
- get_profile() / set_profile() completo — perfil viviente estructurado (user_profile JSON)
- close_session() — genera session_summary + limpia history.db
"""
import httpx
import logging
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import os

COL = timezone(timedelta(hours=-5))

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

# ── SQLite — historial de conversación (se mantiene en SQLite) ────────────────
# El historial turno-a-turno NO va a Mem0 — es acceso secuencial, no semántico.
DB_PATH = Path(__file__).parent.parent / "schemas" / "logs.db"


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            ts TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_turn(user_id: str, role: str, content: str):
    """Guarda un turno de conversación en SQLite."""
    conn = _conn()
    conn.execute(
        "INSERT INTO history (user_id, role, content, ts) VALUES (?, ?, ?, ?)",
        (user_id, role, content, datetime.now(COL).isoformat())
    )
    conn.commit()
    conn.close()


def get_history(user_id: str, limit: int = 10) -> list[dict]:
    """Retorna los últimos N turnos de conversación desde SQLite."""
    conn = _conn()
    rows = conn.execute(
        "SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


# ── Mem0 — memoria semántica ──────────────────────────────────────────────────

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