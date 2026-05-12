"""
Session turn counter — tracks turns per session and triggers summaries.
Stored in logs.db: session_turns table.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

COL = timezone(timedelta(hours=-5))
DB_PATH = Path(__file__).parent.parent / "schemas" / "logs.db"


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def record_turn(session_id: str, user_id: str) -> int:
    """Records a turn for the session. Adds user_id to user_ids if new.
    Returns the new turn_count.
    TODO: multi-user — user_ids JSON array ready for Discord/WhatsApp groups."""
    conn = _conn()
    now = datetime.now(COL).isoformat()

    row = conn.execute(
        "SELECT user_ids, turn_count FROM session_turns WHERE session_id = ?",
        (session_id,)
    ).fetchone()

    if row:
        user_ids = json.loads(row["user_ids"])
        if user_id not in user_ids:
            user_ids.append(user_id)
        new_count = row["turn_count"] + 1
        conn.execute(
            """UPDATE session_turns
               SET user_ids = ?, turn_count = ?, last_turn_at = ?
               WHERE session_id = ?""",
            (json.dumps(user_ids, ensure_ascii=False), new_count, now, session_id),
        )
    else:
        user_ids = [user_id]
        new_count = 1
        conn.execute(
            """INSERT INTO session_turns (session_id, user_ids, turn_count, last_turn_at)
               VALUES (?, ?, ?, ?)""",
            (session_id, json.dumps(user_ids, ensure_ascii=False), new_count, now),
        )

    conn.commit()
    conn.close()
    return new_count


def get_session_users(session_id: str) -> list[str]:
    conn = _conn()
    row = conn.execute(
        "SELECT user_ids FROM session_turns WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row["user_ids"])
    return []


def reset_turns(session_id: str):
    """Deletes the session row after a summary so the next interaction starts fresh."""
    conn = _conn()
    conn.execute("DELETE FROM session_turns WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def get_stale_sessions(inactive_minutes: int = 30) -> list[str]:
    """Return session_ids where last_turn_at is older than inactive_minutes."""
    conn = _conn()
    rows = conn.execute(
        "SELECT session_id, last_turn_at FROM session_turns WHERE last_turn_at IS NOT NULL"
    ).fetchall()
    conn.close()

    now = datetime.now(COL)
    stale = []
    for row in rows:
        last_turn = datetime.fromisoformat(row["last_turn_at"])
        if (now - last_turn).total_seconds() > inactive_minutes * 60:
            stale.append(row["session_id"])
    return stale
