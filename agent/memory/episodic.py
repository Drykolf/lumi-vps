"""
SQLite operations — conversation history, session tracking, summaries.
Stored in data/traces.db via TracesRepository.
"""
import sqlite3
import json
from datetime import datetime, timezone
from agent.subconscious import traces

UTC = timezone.utc


def init_db():
    """Create all SQLite tables for conversation and session tracking (idempotent)."""
    traces.init()


def save_turn(user_id: str, role: str, content: str, session_id: str = "default") -> int:
    """Guarda un turno de conversacion en SQLite. Retorna el history_id."""
    conn = traces.get_conn()
    cur = conn.execute(
        "INSERT INTO history (user_id, role, content, session_id, ts) VALUES (?, ?, ?, ?, ?)",
        (user_id, role, content, session_id, datetime.now(UTC).isoformat())
    )
    conn.commit()
    history_id = cur.lastrowid
    conn.close()
    return history_id


def mark_summarized(session_id: str):
    """Marca como resumidos todos los turnos no resumidos de una sesion."""
    conn = traces.get_conn()
    conn.execute(
        "UPDATE history SET summarized = 1 WHERE session_id = ? AND summarized = 0",
        (session_id,)
    )
    conn.commit()
    conn.close()


def get_unmood_evaluated(since_ts: str, limit: int = 200) -> list[dict]:
    """Rows not yet mood-evaluated since a timestamp, ordered by id."""
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT id, role, content, user_id, session_id, ts
           FROM history
           WHERE mood_evaluated = 0 AND ts >= ?
           ORDER BY id ASC
           LIMIT ?""",
        (since_ts, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_mood_evaluated(max_id: int):
    """Mark all rows up to max_id as mood-evaluated."""
    conn = traces.get_conn()
    conn.execute(
        "UPDATE history SET mood_evaluated = 1 WHERE mood_evaluated = 0 AND id <= ?",
        (max_id,),
    )
    conn.commit()
    conn.close()


def get_unmemory_evaluated(since_ts: str, limit: int = 500) -> list[dict]:
    """Rows not yet memory-evaluated since a timestamp, ordered by id."""
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT id, role, content, user_id, session_id, ts
           FROM history
           WHERE memory_evaluated = 0 AND ts >= ?
           ORDER BY id ASC
           LIMIT ?""",
        (since_ts, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_session_log(session_id: str, include_summarized: bool = False,
                           since_ts: str | None = None, limit: int = 0) -> list[dict]:
    """Retorna los turnos de una sesion, en orden cronologico.
    include_summarized=True incluye turnos ya resumidos.
    since_ts (ISO UTC) filtra desde esa marca temporal.
    limit=0 significa ilimitado; limit>0 retorna los ultimos N."""
    conn = traces.get_conn()
    columns = "role, content, user_id, ts"
    where = f"session_id = ?{' AND summarized = 0' if not include_summarized else ''}"
    params = [session_id]

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
                         exclude_session_id: str | None = None,
                         include_summarized: bool = False,
                         limit: int = 10) -> list[dict]:
    """Retorna los ultimos turnos de un usuario a traves de sesiones.
    since_ts (ISO UTC) filtra desde esa marca temporal.
    exclude_session_id excluye una sesion especifica (para cross-session).
    Retorna role, content, session_id, ts en orden cronologico."""
    conn = traces.get_conn()
    columns = "role, content, session_id, ts"
    where = f"user_id = ?{' AND summarized = 0' if not include_summarized else ''}"
    params = [user_id]

    if since_ts:
        where += " AND ts >= ?"
        params.append(since_ts)

    if exclude_session_id:
        where += " AND session_id != ?"
        params.append(exclude_session_id)

    rows = conn.execute(
        f"""SELECT role, content, session_id, ts FROM (
                SELECT id, {columns} FROM history
                WHERE {where}
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC""",
        params + [limit],
    ).fetchall()

    conn.close()
    return [{"role": r[0], "content": r[1], "session_id": r[2], "ts": r[3]} for r in rows]


def mark_memory_evaluated(max_id: int):
    """Mark all rows up to max_id as memory-evaluated."""
    conn = traces.get_conn()
    conn.execute(
        "UPDATE history SET memory_evaluated = 1 WHERE memory_evaluated = 0 AND id <= ?",
        (max_id,),
    )
    conn.commit()
    conn.close()


def add_mood_log(state: dict, trigger_source: str,
                 session_id: str | None = None,
                 note: str | None = None):
    conn = traces.get_conn()
    conn.execute(
        """INSERT INTO mood_logs
           (ts, trigger_source, session_id, mood_valence, mood_energy,
            irritation, focus_level, presence_need, state_label,
            emotional_honesty_mode, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(UTC).isoformat(),
            trigger_source,
            session_id,
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
    period_start: datetime,
    period_end: datetime,
    talked_at_ts: datetime,
    thread_span_minutes: int | None,
    user_ids: list[str],
    topic_label: str | None,
    summary: str,
    lumi_state: dict | None,
    entry_type: str = "daily_thread",
) -> int:
    """Insert a single diary entry into traces.db. Returns the new row id."""
    conn = traces.get_conn()
    cur = conn.execute(
        """INSERT INTO diary
           (period_start, period_end, talked_at_ts, thread_span_minutes,
            user_ids, topic_label, summary, lumi_state, entry_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            period_start.isoformat(),
            period_end.isoformat(),
            talked_at_ts.isoformat(),
            thread_span_minutes,
            json.dumps(user_ids, ensure_ascii=False),
            topic_label,
            summary,
            json.dumps(lumi_state, ensure_ascii=False) if lumi_state else None,
            entry_type,
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


async def read_recent_diary_entries(
    user_id: str | None = None,
    limit: int = 7,
    entry_type: str | None = "daily_thread",
) -> list[dict]:
    """Return the most recent diary entries, newest first.
    If user_id is provided, filter by user_ids JSON array.
    If entry_type is None, all entry types are returned.
    Returns parsed fields: datetimes as datetime objects, user_ids as list,
    lumi_state as dict or None."""
    conn = traces.get_conn()
    where = ""
    params: list = []

    if entry_type is not None:
        where += " WHERE entry_type = ?"
        params.append(entry_type)

    if user_id is not None:
        where += f" {'AND' if where else 'WHERE'} user_ids LIKE ?"
        params.append(f'%"{user_id}"%')

    rows = conn.execute(
        f"""SELECT id, period_start, period_end, talked_at_ts, thread_span_minutes,
                   user_ids, topic_label, summary, lumi_state, entry_type, created_at
            FROM diary{where}
            ORDER BY period_end DESC, talked_at_ts DESC
            LIMIT ?""",
        params + [limit],
    ).fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "id": r[0],
            "period_start": datetime.fromisoformat(r[1]),
            "period_end": datetime.fromisoformat(r[2]),
            "talked_at_ts": datetime.fromisoformat(r[3]),
            "thread_span_minutes": r[4],
            "user_ids": json.loads(r[5]) if r[5] else [],
            "topic_label": r[6],
            "summary": r[7],
            "lumi_state": json.loads(r[8]) if r[8] else None,
            "entry_type": r[9],
            "created_at": datetime.fromisoformat(r[10]) if r[10] else None,
        })

    return results
