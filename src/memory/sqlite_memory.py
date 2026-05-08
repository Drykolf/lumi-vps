import sqlite3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

COL = timezone(timedelta(hours=-5))

DB_PATH = Path(__file__).parent.parent / "schemas" / "logs.db"


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO history (user_id, role, content, ts) VALUES (?, ?, ?, ?)",
        (user_id, role, content, datetime.now(COL).isoformat())
    )
    conn.commit()
    conn.close()


def get_history(user_id: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
