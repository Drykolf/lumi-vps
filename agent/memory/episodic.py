"""
SQLite operations — conversation history, session tracking, summaries.
Stored in data/logs.db (repo root).
"""
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

COL = timezone(timedelta(hours=-5))
DB_PATH = Path(__file__).parent.parent.parent / "data" / "logs.db"


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create all SQLite tables for conversation and session tracking."""
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT 'default',
            summarized INTEGER NOT NULL DEFAULT 0,
            ts TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_turns (
            session_id   TEXT PRIMARY KEY,
            user_ids     TEXT NOT NULL DEFAULT '[]',
            turn_count   INTEGER NOT NULL DEFAULT 0,
            last_turn_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_summaries (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_ids   TEXT NOT NULL,
            summary    TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_summaries_user ON session_summaries(user_ids)"
    )
    conn.commit()
    conn.close()


def save_turn(user_id: str, role: str, content: str, session_id: str = "default"):
    """Guarda un turno de conversacion en SQLite."""
    conn = _conn()
    conn.execute(
        "INSERT INTO history (user_id, role, content, session_id, ts) VALUES (?, ?, ?, ?, ?)",
        (user_id, role, content, session_id, datetime.now(COL).isoformat())
    )
    conn.commit()
    conn.close()


def get_history(user_id: str, limit: int = 10) -> list[dict]:
    """Retorna los ultimos N turnos de conversacion desde SQLite."""
    conn = _conn()
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
    conn = _conn()
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
    conn = _conn()
    conn.execute(
        "UPDATE history SET summarized = 1 WHERE session_id = ? AND summarized = 0",
        (session_id,)
    )
    conn.commit()
    conn.close()
