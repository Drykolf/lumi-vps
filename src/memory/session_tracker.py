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
    """Resets turn_count to 0 after a summary is generated."""
    conn = _conn()
    conn.execute(
        "UPDATE session_turns SET turn_count = 0 WHERE session_id = ?",
        (session_id,)
    )
    conn.commit()
    conn.close()
