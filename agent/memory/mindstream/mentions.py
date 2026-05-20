"""
Person mentions — per-turn entity mention tracking for resolution and consolidation.
Stored in traces.db: person_mentions table.
"""
import json
from datetime import datetime, timezone, timedelta
from agent.subconscious import traces

UTC = timezone.utc


def add_mention(
    entity: dict,
    history_id: int,
    user_id: str,
    session_id: str,
    source_role: str = "user",
) -> dict | None:
    """Persist one detected entity mention from _entities_check output.
    Returns the inserted row as dict, or None on failure."""
    conn = traces.get_conn()
    now = datetime.now(UTC).isoformat()
    extractor_json = json.dumps(entity, ensure_ascii=False)

    cur = conn.execute(
        """INSERT INTO person_mentions
           (history_id, user_id, session_id, source_role,
            raw_text, mention_type, raw_name, normalized_name,
            descriptor, relation_label_hint, anchor, confidence,
            extractor_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            history_id,
            user_id,
            session_id,
            source_role,
            entity.get("raw_text", ""),
            entity.get("mention_type", "named_person"),
            entity.get("raw_name"),
            entity.get("normalized_name"),
            entity.get("descriptor"),
            entity.get("relation_label_hint"),
            entity.get("anchor"),
            entity.get("confidence", 1.0),
            extractor_json,
            now,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM person_mentions WHERE mention_id = ?",
        (cur.lastrowid,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_mention_resolution(
    mention_id: int,
    status: str,
    resolved_person_id: str | None = None,
    candidates: list[dict] | None = None,
) -> dict | None:
    """Stamp resolution result on a previously-added mention row.
    Leaves consolidation_status='pending' for nightly quiescence to pick up."""
    conn = traces.get_conn()
    now = datetime.now(UTC).isoformat()
    candidates_json = json.dumps(candidates, ensure_ascii=False) if candidates else None
    conn.execute(
        """UPDATE person_mentions
           SET resolution_status = ?,
               resolved_person_id = ?,
               candidates_json = ?,
               resolved_at = ?
           WHERE mention_id = ?""",
        (status, resolved_person_id, candidates_json, now, mention_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM person_mentions WHERE mention_id = ?", (mention_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_recent_mentions(hours_ago: float = 24.0, limit: int = 500) -> list[dict]:
    """Get mentions created in the last N hours, newest first."""
    cutoff = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT * FROM person_mentions
           WHERE created_at >= ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (cutoff, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user_mentions(user_id: str, limit: int = 100) -> list[dict]:
    """Get all mentions spoken by a specific user, newest first."""
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT * FROM person_mentions
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
