"""
SQLite operations — conversation history, session tracking, summaries.
Stored in data/traces.db via TracesRepository.
"""
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from agent.subconscious import traces

COL = timezone(timedelta(hours=-5))


def init_db():
    """Create all SQLite tables for conversation and session tracking (idempotent)."""
    traces.init()


def save_turn(user_id: str, role: str, content: str, session_id: str = "default"):
    """Guarda un turno de conversacion en SQLite."""
    conn = traces.get_conn()
    conn.execute(
        "INSERT INTO history (user_id, role, content, session_id, ts) VALUES (?, ?, ?, ?, ?)",
        (user_id, role, content, session_id, datetime.now(COL).isoformat())
    )
    conn.commit()
    conn.close()


def get_history(user_id: str, limit: int = 10) -> list[dict]:
    """Retorna los ultimos N turnos de conversacion desde SQLite."""
    conn = traces.get_conn()
    rows = conn.execute(
        "SELECT role, content FROM history WHERE user_id = ? AND summarized = 0 ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def get_session_turns(session_id: str, include_summarized: bool = False,
                      limit: int = 0) -> list[dict]:
    """Retorna los turnos de una sesion, en orden cronologico.
    include_summarized=True incluye turnos ya resumidos.
    limit=0 significa ilimitado."""
    conn = traces.get_conn()
    columns = "role, content, user_id"
    where = f"session_id = ?{' AND summarized = 0' if not include_summarized else ''}"
    limit_sql = f"LIMIT {limit}" if limit else ""
    rows = conn.execute(
        f"SELECT {columns} FROM history WHERE {where} ORDER BY id ASC {limit_sql}",
        (session_id,)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1], "user_id": r[2]} for r in rows]


def mark_summarized(session_id: str):
    """Marca como resumidos todos los turnos no resumidos de una sesion."""
    conn = traces.get_conn()
    conn.execute(
        "UPDATE history SET summarized = 1 WHERE session_id = ? AND summarized = 0",
        (session_id,)
    )
    conn.commit()
    conn.close()
