"""
SQLite operations — conversation history, channel tracking, summaries.
Stored in data/traces.db via TracesRepository.
"""
import sqlite3
import json
from datetime import datetime, timedelta, timezone
from agent.subconscious import traces

UTC = timezone.utc


def init_db():
    """Create all SQLite tables for conversation and channel tracking (idempotent)."""
    traces.init()


def save_turn(user_id: str, role: str, content: str, channel_id: str = "default") -> int:
    """Guarda un turno de conversacion en SQLite. Retorna el history_id."""
    conn = traces.get_conn()
    cur = conn.execute(
        "INSERT INTO history (user_id, role, content, channel_id, ts) VALUES (?, ?, ?, ?, ?)",
        (user_id, role, content, channel_id, datetime.now(UTC).isoformat())
    )
    conn.commit()
    history_id = cur.lastrowid
    conn.close()
    return history_id


def get_history_since(since_ts: str, limit: int = 200) -> list[dict]:
    """All history rows since a timestamp, ordered by id. Used by mood_check."""
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT id, role, content, user_id, channel_id, ts
           FROM history
           WHERE ts >= ?
           ORDER BY id ASC
           LIMIT ?""",
        (since_ts, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_channel_log(channel_id: str,
                           since_ts: str | None = None, limit: int = 0) -> list[dict]:
    """Retorna los turnos de un canal, en orden cronologico.
    since_ts (ISO UTC) filtra desde esa marca temporal.
    limit=0 significa ilimitado; limit>0 retorna los ultimos N."""
    conn = traces.get_conn()
    columns = "role, content, user_id, ts"
    where = "channel_id = ?"
    params = [channel_id]

    if since_ts:
        where += " AND ts >= ?"
        params.append(since_ts)

    if limit:
        rows = conn.execute(
            f"""SELECT role, content, user_id, ts FROM (
                    SELECT id, {columns} FROM history
                    WHERE {where}
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC""",
            params + [limit],
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {columns} FROM history WHERE {where} ORDER BY id ASC",
            params,
        ).fetchall()

    conn.close()
    return [{"role": r[0], "content": r[1], "user_id": r[2], "ts": r[3]} for r in rows]


def get_recent_user_log(user_id: str, since_ts: str | None = None,
                         exclude_channel_id: str | None = None,
                         limit: int = 10) -> list[dict]:
    """Retorna los ultimos turnos de un usuario a traves de canales.
    since_ts (ISO UTC) filtra desde esa marca temporal.
    exclude_channel_id excluye un canal especifico (para cross-channel).
    Retorna role, content, user_id, channel_id, ts en orden cronologico."""
    conn = traces.get_conn()
    columns = "role, content, user_id, channel_id, ts"
    where = "user_id = ?"
    params = [user_id]

    if since_ts:
        where += " AND ts >= ?"
        params.append(since_ts)

    if exclude_channel_id:
        where += " AND channel_id != ?"
        params.append(exclude_channel_id)

    rows = conn.execute(
        f"""SELECT role, content, user_id, channel_id, ts FROM (
                SELECT id, {columns} FROM history
                WHERE {where}
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC""",
        params + [limit],
    ).fetchall()

    conn.close()
    return [{"role": r[0], "content": r[1], "user_id": r[2], "channel_id": r[3], "ts": r[4]} for r in rows]


def add_mood_log(state: dict, trigger_source: str,
                 channel_id: str | None = None,
                 note: str | None = None):
    conn = traces.get_conn()
    conn.execute(
        """INSERT INTO mood_logs
           (ts, trigger_source, channel_id, mood_valence, mood_energy,
            irritation, focus_level, presence_need, state_label,
            emotional_honesty_mode, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(UTC).isoformat(),
            trigger_source,
            channel_id,
            state.get("mood_valence", 0.3),
            state.get("mood_energy", 0.6),
            state.get("irritation", 0.1),
            state.get("focus_level", 0.7),
            state.get("presence_need", 0.0),
            state.get("state_label", "centered"),
            int(state.get("emotional_honesty_mode", False)),
            note,
        ),
    )
    conn.commit()
    conn.close()


async def write_diary_entry(
    date: str,
    people: list[str],
    threads: list[str],
    page: str,
    mood: dict | None,
    entry_type: str = "daily_page",
) -> int:
    """Upsert the diary page for `date` (YYYY-MM-DD) into traces.db.

    `date` is UNIQUE, so a re-run for the same day overwrites the prior page
    (idempotent self-healing). Returns the row id."""
    conn = traces.get_conn()
    cur = conn.execute(
        """INSERT OR REPLACE INTO diary
           (date, people, threads, page, mood, entry_type)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            date,
            json.dumps(people, ensure_ascii=False),
            json.dumps(threads, ensure_ascii=False),
            page,
            json.dumps(mood, ensure_ascii=False) if mood else None,
            entry_type,
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def get_history_grouped_by_channel(start_ts: str, end_ts: str) -> dict[str, list[dict]]:
    """Return history rows in [start_ts, end_ts) grouped by channel_id, each
    list ordered chronologically. Used by nightly consolidation to feed
    transcripts to the LLM."""
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT id, user_id, role, content, channel_id, ts
           FROM history
           WHERE ts >= ? AND ts < ?
           ORDER BY ts ASC""",
        (start_ts, end_ts),
    ).fetchall()
    conn.close()

    grouped: dict[str, list[dict]] = {}
    for r in rows:
        cid = r[4]
        grouped.setdefault(cid, []).append({
            "history_id": r[0],
            "user_id": r[1],
            "role": r[2],
            "content": r[3],
            "ts": r[5],
        })
    return grouped


def get_active_user_ids_in_period(period_start: str, period_end: str) -> list[str]:
    """Distinct non-assistant user_ids that appear in history in [period_start, period_end)."""
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT DISTINCT user_id FROM history
           WHERE role = 'user' AND ts >= ? AND ts < ?""",
        (period_start, period_end),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_turns_in_period_by_user(
    user_id: str,
    period_start: str,
    period_end: str,
    limit: int = 12,
) -> list[dict]:
    """History rows for a specific user in [period_start, period_end), most
    recent `limit` turns, returned in chronological order. Format matches
    get_turns_by_ids so it can be used as turn_excerpts in consolidation payloads."""
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT id, user_id, role, content, channel_id, ts
           FROM history
           WHERE user_id = ? AND ts >= ? AND ts < ?
           ORDER BY ts DESC LIMIT ?""",
        (user_id, period_start, period_end, limit),
    ).fetchall()
    conn.close()
    return [
        {"history_id": r[0], "user_id": r[1], "role": r[2], "content": r[3], "channel_id": r[4], "ts": r[5]}
        for r in reversed(rows)
    ]


def get_channel_context_for_user_in_period(
    user_id: str,
    period_start: str,
    period_end: str,
    limit: int = 12,
) -> list[dict]:
    """Full channel context for a user active in [period_start, period_end).

    Finds the channels the user participated in, then returns up to `limit`
    turns from those channels including ALL participants (other users, Lumi)
    so the LLM has enough context to evaluate the interaction. Returns the
    most recent `limit` turns, chronologically ordered.

    Use this instead of get_turns_in_period_by_user when context matters —
    e.g. "sí claro" is meaningless without knowing what was asked.
    """
    conn = traces.get_conn()
    channel_rows = conn.execute(
        """SELECT DISTINCT channel_id FROM history
           WHERE user_id = ? AND ts >= ? AND ts < ?""",
        (user_id, period_start, period_end),
    ).fetchall()
    if not channel_rows:
        conn.close()
        return []

    channels = [r[0] for r in channel_rows]
    placeholders = ",".join("?" for _ in channels)
    rows = conn.execute(
        f"""SELECT id, user_id, role, content, channel_id, ts
            FROM history
            WHERE channel_id IN ({placeholders})
              AND ts >= ? AND ts < ?
            ORDER BY ts DESC LIMIT ?""",
        tuple(channels) + (period_start, period_end, limit),
    ).fetchall()
    conn.close()
    return [
        {"history_id": r[0], "user_id": r[1], "role": r[2], "content": r[3], "channel_id": r[4], "ts": r[5]}
        for r in reversed(rows)
    ]


def get_turns_by_ids(history_ids: list[int]) -> list[dict]:
    """Fetch specific history rows by id, chronologically ordered. Empty list
    on empty input."""
    if not history_ids:
        return []
    placeholders = ",".join("?" for _ in history_ids)
    conn = traces.get_conn()
    rows = conn.execute(
        f"""SELECT id, user_id, role, content, channel_id, ts
            FROM history
            WHERE id IN ({placeholders})
            ORDER BY ts ASC""",
        tuple(history_ids),
    ).fetchall()
    conn.close()
    return [
        {
            "history_id": r[0],
            "user_id": r[1],
            "role": r[2],
            "content": r[3],
            "channel_id": r[4],
            "ts": r[5],
        }
        for r in rows
    ]


def get_mood_logs_since(start_ts: str) -> list[dict]:
    """Mood snapshots since a given UTC ISO-8601 timestamp, chronological."""
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT ts, mood_valence, mood_energy, irritation, focus_level,
                  presence_need, state_label, emotional_honesty_mode
           FROM mood_logs
           WHERE ts >= ?
           ORDER BY ts ASC""",
        (start_ts,),
    ).fetchall()
    conn.close()
    return [
        {
            "ts": r[0],
            "mood_valence": r[1],
            "mood_energy": r[2],
            "irritation": r[3],
            "focus_level": r[4],
            "presence_need": r[5],
            "state_label": r[6],
            "emotional_honesty_mode": bool(r[7]),
        }
        for r in rows
    ]


async def read_recent_diary_entries(
    user_id: str | None = None,
    limit: int = 7,
    entry_type: str | None = "daily_page",
) -> list[dict]:
    """Return the most recent diary pages, newest first (by date).
    If user_id is provided, filter by the `people` JSON array.
    If entry_type is None, all entry types are returned.
    Returns parsed fields: people/threads as lists, mood as dict or None."""
    conn = traces.get_conn()
    where = ""
    params: list = []

    if entry_type is not None:
        where += " WHERE entry_type = ?"
        params.append(entry_type)

    if user_id is not None:
        where += f" {'AND' if where else 'WHERE'} people LIKE ?"
        params.append(f'%"{user_id}"%')

    rows = conn.execute(
        f"""SELECT id, date, people, threads, page, mood, entry_type, created_at
            FROM diary{where}
            ORDER BY date DESC
            LIMIT ?""",
        params + [limit],
    ).fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "id": r[0],
            "date": r[1],
            "people": json.loads(r[2]) if r[2] else [],
            "threads": json.loads(r[3]) if r[3] else [],
            "page": r[4],
            "mood": json.loads(r[5]) if r[5] else None,
            "entry_type": r[6],
            "created_at": datetime.fromisoformat(r[7]) if r[7] else None,
        })

    return results


def get_diary_as_book(days: int = 2) -> str:
    """Return recent diary pages formatted as dated journal entries.

    Fetches `daily_page` entries from the last `days` calendar days (UTC) and
    formats them as plain text — one date header per day followed by that day's
    page. Returns an empty string when no pages exist in the window.

    Intended for injection into the diary-generation prompt so the model can
    maintain continuity of voice and avoid repeating topics.
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).date().isoformat()  # 'YYYY-MM-DD'

    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT date, page
           FROM diary
           WHERE entry_type = 'daily_page'
             AND date >= ?
           ORDER BY date ASC""",
        (cutoff,),
    ).fetchall()
    conn.close()

    if not rows:
        return ""

    pages = [f"{date_str}\n{page}" for date_str, page in rows]
    return "\n\n---\n\n".join(pages)
