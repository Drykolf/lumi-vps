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
    """Persist one detected entity mention from turn_frame_check output.
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


def get_pending() -> list[dict]:
    """All mentions waiting for nightly consolidation, oldest first."""
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT * FROM person_mentions
           WHERE consolidation_status = 'pending'
           ORDER BY created_at ASC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_consolidated(mention_id: int) -> None:
    """Stamp consolidation_status='consolidated' + consolidated_at=now."""
    conn = traces.get_conn()
    conn.execute(
        """UPDATE person_mentions
           SET consolidation_status = 'consolidated',
               consolidated_at = ?
           WHERE mention_id = ?""",
        (datetime.now(UTC).isoformat(), mention_id),
    )
    conn.commit()
    conn.close()


def update_consolidation_status(mention_id: int, status: str) -> None:
    """Set consolidation_status to one of: pending|consolidated|skipped|needs_review."""
    conn = traces.get_conn()
    conn.execute(
        "UPDATE person_mentions SET consolidation_status = ? WHERE mention_id = ?",
        (status, mention_id),
    )
    conn.commit()
    conn.close()


def delete_mention(mention_id: int) -> None:
    """Remove a mention row entirely. Used for anonymous/irrelevant mentions
    that the nightly consolidator decides not to keep."""
    conn = traces.get_conn()
    conn.execute("DELETE FROM person_mentions WHERE mention_id = ?", (mention_id,))
    conn.commit()
    conn.close()


def get_resolved_mentions_by_history_ids(history_ids: list[int]) -> list[dict]:
    """Resolved mentions for a list of history row ids, used by mood_check."""
    if not history_ids:
        return []
    placeholders = ",".join("?" for _ in history_ids)
    conn = traces.get_conn()
    rows = conn.execute(
        f"""SELECT * FROM person_mentions
            WHERE history_id IN ({placeholders})
              AND resolution_status = 'resolved'
              AND resolved_person_id IS NOT NULL
            ORDER BY created_at ASC""",
        tuple(history_ids),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_consolidated_grouped_by_person(person_ids: set[str]) -> dict[str, list[dict]]:
    """Return all consolidated mentions for the given person_ids, grouped by
    resolved_person_id. Empty set → empty dict."""
    if not person_ids:
        return {}
    placeholders = ",".join("?" for _ in person_ids)
    conn = traces.get_conn()
    rows = conn.execute(
        f"""SELECT * FROM person_mentions
            WHERE consolidation_status = 'consolidated'
              AND resolved_person_id IN ({placeholders})
            ORDER BY created_at ASC""",
        tuple(person_ids),
    ).fetchall()
    conn.close()

    grouped: dict[str, list[dict]] = {}
    for r in rows:
        d = dict(r)
        pid = d["resolved_person_id"]
        grouped.setdefault(pid, []).append(d)
    return grouped


def get_consolidated_since_grouped_by_person(
    period_start: datetime,
) -> dict[str, list[dict]]:
    """Return consolidated mentions stamped on/after period_start, grouped by
    resolved_person_id. Used by nightly step 2 to process only the slice of
    mentions consolidated since the last successful run — supports self-healing
    when prior nights' step 2 failed (the window stretches back automatically)."""
    conn = traces.get_conn()
    rows = conn.execute(
        """SELECT * FROM person_mentions
           WHERE consolidation_status = 'consolidated'
             AND resolved_person_id IS NOT NULL
             AND consolidated_at >= ?
           ORDER BY created_at ASC""",
        (period_start.isoformat(),),
    ).fetchall()
    conn.close()

    grouped: dict[str, list[dict]] = {}
    for r in rows:
        d = dict(r)
        pid = d["resolved_person_id"]
        grouped.setdefault(pid, []).append(d)
    return grouped
