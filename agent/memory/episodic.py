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
