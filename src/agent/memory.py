"""
Cliente de memoria — Fase 3: SQLite placeholder.
Fase 4: reemplazar con cliente Mem0 + Apache AGE.
La interfaz pública no cambia entre fases.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "logs" / "memory.db"


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
    conn = _conn()
    conn.execute(
        "INSERT INTO history (user_id, role, content, ts) VALUES (?, ?, ?, ?)",
        (user_id, role, content, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def get_history(user_id: str, limit: int = 10) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def search_relevant(user_id: str, query: str, limit: int = 5) -> list[str]:
    """Fase 3: retorna vacío. Fase 4: Mem0 semantic search."""
    return []
