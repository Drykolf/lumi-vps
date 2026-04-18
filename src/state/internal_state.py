import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "logs" / "memory.db"


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_state_table():
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS internal_state (
            user_id TEXT PRIMARY KEY,
            mood TEXT DEFAULT 'neutral',
            energy TEXT DEFAULT 'normal',
            focus TEXT DEFAULT 'available',
            updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_state(user_id: str) -> dict:
    conn = _conn()
    row = conn.execute(
        "SELECT mood, energy, focus FROM internal_state WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    if row:
        return {"mood": row[0], "energy": row[1], "focus": row[2]}
    return {"mood": "neutral", "energy": "normal", "focus": "available"}


def update_state(user_id: str, mood: str = None, energy: str = None, focus: str = None):
    current = get_state(user_id)
    new_state = {
        "mood": mood or current["mood"],
        "energy": energy or current["energy"],
        "focus": focus or current["focus"],
    }
    conn = _conn()
    conn.execute("""
        INSERT INTO internal_state (user_id, mood, energy, focus, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            mood=excluded.mood,
            energy=excluded.energy,
            focus=excluded.focus,
            updated_at=excluded.updated_at
    """, (user_id, new_state["mood"], new_state["energy"], new_state["focus"],
          datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def state_to_text(state: dict) -> str:
    return f"Estado actual: {state['mood']}, energía {state['energy']}, enfoque {state['focus']}."

