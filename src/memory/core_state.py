"""
Core state database — person_interest, user_profiles, relations, lumi_state.
Implements interest_policy.md and relation_policy.md storage layer.

Tables (from 00_schema_sqlite.sql):
  person_interest  — Lumi's emotional calculus toward each person
  user_profiles    — structured static data about users (JSON)
  relations        — directed connections between third parties
  lumi_state       — Lumi's own dynamic internal state (JSON)
  skill_proposals  — pending skill evolution drafts

Uses core_state.db (separate from logs.db for conversation history).
"""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "schemas" / "core_state.db"
SCHEMA_PATH = Path(__file__).parent.parent / "skills" / "_impl" / "00_schema_sqlite.sql"


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_core_db():
    """Create core_state.db and run the full schema (idempotent)."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = _conn()
    conn.executescript(sql)
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Public API — use these from outside this module
# ═══════════════════════════════════════════════════════════════════════════════

def get_user_information(user_id: str) -> dict:
    """Returns {profile: dict|None, interest: dict|None} in one call."""
    return {
        "profile": _get_user_profile(user_id),
        "interest": _get_person(user_id),
    }


def set_user_information(user_id: str, profile: dict = None,
                         interest: dict = None):
    """Update profile JSON and/or interest fields for a user."""
    if profile is not None:
        _set_user_profile(user_id, profile)
    if interest is not None:
        _update_person_interest(user_id, **interest)


def create_person_interest(person_id: str, is_jose: int = 0,
                           interest_score: float = 0.10) -> dict:
    """Create an interest row for a new person."""
    conn = _conn()
    conn.execute(
        """INSERT OR IGNORE INTO person_interest (person_id, is_jose, interest_score)
           VALUES (?, ?, ?)""",
        (person_id, is_jose, interest_score),
    )
    conn.commit()
    conn.close()
    return _get_person(person_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Private — person interest
# ═══════════════════════════════════════════════════════════════════════════════

def _get_person(person_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM person_interest WHERE person_id = ?", (person_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _update_person_interest(person_id: str, **kwargs) -> dict | None:
    allowed = {"interest_score", "emotional_tone", "status",
               "notes", "session_delta"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return _get_person(person_id)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [person_id]
    conn = _conn()
    conn.execute(
        f"UPDATE person_interest SET {set_clause} WHERE person_id = ?", values
    )
    conn.commit()
    conn.close()
    return _get_person(person_id)


def _increment_mention(person_id: str):
    conn = _conn()
    conn.execute(
        """UPDATE person_interest
           SET mention_count = mention_count + 1,
               last_mentioned = datetime('now')
           WHERE person_id = ?""",
        (person_id,),
    )
    conn.commit()
    conn.close()


def _list_active_persons() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM person_interest WHERE status != 'forgotten' ORDER BY interest_score DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# Interest deltas (interest_policy.md)
# ═══════════════════════════════════════════════════════════════════════════════

def add_delta(person_id: str, delta: float,
              is_rehabilitation: bool = False) -> dict | None:
    """Apply an interest delta per turn. Enforces per-session caps and score
    boundaries. Updates interest_score immediately; accumulates to
    session_delta for auditing."""
    person = _get_person(person_id)
    if not person:
        return None

    is_jose = person["is_jose"] == 1
    current_score = person["interest_score"]
    current_sd = person["session_delta"]

    if is_jose:
        # Jose: floor at 0.70, no ceiling
        new_score = max(current_score + delta, 0.70)
        effective = delta
    else:
        if delta > 0 and is_rehabilitation and current_score < 0:
            # Rehab cap: cannot push score above 0.0
            effective = min(delta, -current_score)
        elif delta > 0:
            # Normal positive: per-session cap at +0.05 (non-rehab)
            remaining = 0.05 - current_sd
            if remaining <= 0:
                return person
            effective = min(delta, remaining)
        else:
            # Negative deltas have no floor cap, no session cap
            effective = delta

        # Absolute cap: non-Jose cannot exceed 0.69
        new_score = min(current_score + effective, 0.69)
        new_score = max(new_score, -1.0)

    if effective == 0:
        return person

    conn = _conn()
    conn.execute(
        """UPDATE person_interest
           SET interest_score = ?,
               session_delta = session_delta + ?,
               last_mentioned = datetime('now')
           WHERE person_id = ?""",
        (new_score, effective, person_id),
    )
    conn.commit()
    conn.close()

    _recalc_status(person_id, new_score)
    return get_person(person_id)


def _recalc_status(person_id: str, score: float):
    """Update status triggered by score crossing thresholds."""
    conn = _conn()
    row = conn.execute(
        "SELECT status FROM person_interest WHERE person_id = ?", (person_id,)
    ).fetchone()
    if not row or row["status"] == "forgotten":
        conn.close()
        return

    current = row["status"]
    if score < 0 and current != "disliked":
        conn.execute(
            "UPDATE person_interest SET status = 'disliked' WHERE person_id = ?",
            (person_id,),
        )
    elif score >= 0 and current == "disliked":
        conn.execute(
            "UPDATE person_interest SET status = 'active' WHERE person_id = ?",
            (person_id,),
        )
    conn.commit()
    conn.close()


def commit_session_close():
    """Reset all session_delta values to 0. Called at session end.
    interest_scores have already been updated turn-by-turn."""
    conn = _conn()
    conn.execute("UPDATE person_interest SET session_delta = 0.0 WHERE session_delta != 0.0")
    conn.commit()
    conn.close()


def run_decay():
    """Apply decay to interest scores per interest_policy.md.
    Runs at session close and weekly heartbeat.
    Non-Jose only, score >= 0, last mentioned 28+ days ago."""
    sql = (Path(__file__).parent.parent / "skills" / "_impl" / "interest_decay.sql")
    script = sql.read_text(encoding="utf-8")
    conn = _conn()
    conn.executescript(script)
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Private — user profiles
# ═══════════════════════════════════════════════════════════════════════════════

def _get_user_profile(user_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT data FROM user_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row["data"])
    return None


def _set_user_profile(user_id: str, data: dict):
    from datetime import datetime, timezone, timedelta
    COL = timezone(timedelta(hours=-5))
    now = datetime.now(COL).isoformat()
    conn = _conn()
    conn.execute(
        """INSERT INTO user_profiles (user_id, data, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               data = excluded.data, updated_at = excluded.updated_at""",
        (user_id, json.dumps(data, ensure_ascii=False), now),
    )
    conn.commit()
    conn.close()


def find_user_id_by_name(name: str) -> str | None:
    """Search user_profiles JSON for matching name or alias."""
    conn = _conn()
    rows = conn.execute("SELECT user_id, data FROM user_profiles").fetchall()
    conn.close()
    for row in rows:
        data = json.loads(row["data"])
        if data.get("name") == name or name in data.get("aliases", []):
            return row["user_id"]
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Relations (relation_policy.md)
# ═══════════════════════════════════════════════════════════════════════════════

def add_relation(from_person_id: str, to_person_id: str,
                 relation_type: str, description: str,
                 inferred: int = 0) -> dict | None:
    """Create a directed relation between two person_ids.
    Never stores relations involving 'lumi' (enforced by schema CHECK)."""
    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO relations
               (from_person_id, to_person_id, relation_type,
                description, inferred)
               VALUES (?, ?, ?, ?, ?)""",
            (from_person_id, to_person_id, relation_type,
             description, inferred),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM relations WHERE rowid = last_insert_rowid()"
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.IntegrityError:
        conn.close()
        return None


def get_relations(person_id: str) -> list[dict]:
    """Get all relations where person_id appears as from or to."""
    conn = _conn()
    rows = conn.execute(
        """SELECT * FROM relations
           WHERE from_person_id = ? OR to_person_id = ?
           ORDER BY mention_count DESC""",
        (person_id, person_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_relation_between(id1: str, id2: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        """SELECT * FROM relations
           WHERE (from_person_id = ? AND to_person_id = ?)
              OR (from_person_id = ? AND to_person_id = ?)""",
        (id1, id2, id2, id1),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_relation(relation_id: int):
    conn = _conn()
    conn.execute("DELETE FROM relations WHERE relation_id = ?", (relation_id,))
    conn.commit()
    conn.close()


def increment_relation_mention(from_person_id: str, to_person_id: str):
    conn = _conn()
    conn.execute(
        """UPDATE relations
           SET mention_count = mention_count + 1,
               last_mentioned = datetime('now')
           WHERE from_person_id = ? AND to_person_id = ?""",
        (from_person_id, to_person_id),
    )
    conn.commit()
    conn.close()


def infer_family_relations() -> list[dict]:
    """Apply the 4 inference rules from relation_policy.md (direct family only).
    Inserts inferred relations with inferred=1. Returns newly created rows."""
    new_rows = []

    def _infer_if_missing(from_id, to_id, rtype, desc):
        existing = get_relation_between(from_id, to_id)
        if existing:
            return None
        return add_relation(from_id, to_id, rtype, desc, inferred=1)

    conn = _conn()
    families = conn.execute(
        "SELECT from_person_id, to_person_id, description FROM relations WHERE relation_type = 'family'"
    ).fetchall()
    conn.close()

    is_parent_of_jose = set()
    is_sibling_of_jose = set()

    for r in families:
        fid, tid, desc = r["from_person_id"], r["to_person_id"], r["description"]
        if tid == "jose":
            if "madre" in desc.lower() or "padre" in desc.lower() or "mamá" in desc.lower() or "papá" in desc.lower():
                is_parent_of_jose.add(fid)
            if "herman" in desc.lower():
                is_sibling_of_jose.add(fid)
        if fid == "jose":
            if "madre" in desc.lower() or "padre" in desc.lower() or "mamá" in desc.lower() or "papá" in desc.lower():
                is_parent_of_jose.add(tid)
            if "herman" in desc.lower():
                is_sibling_of_jose.add(tid)

    parent_list = list(is_parent_of_jose)
    if len(parent_list) >= 2:
        for i in range(len(parent_list)):
            for j in range(i + 1, len(parent_list)):
                r = _infer_if_missing(
                    parent_list[i], parent_list[j], "romantic",
                    f"{parent_list[i]} y {parent_list[j]} son los padres de Jose",
                )
                if r:
                    new_rows.append(r)

    for parent in is_parent_of_jose:
        for sibling in is_sibling_of_jose:
            r = _infer_if_missing(
                parent, sibling, "family",
                f"{parent} es padre/madre de {sibling}",
            )
            if r:
                new_rows.append(r)

    sibling_list = list(is_sibling_of_jose)
    if len(sibling_list) >= 2:
        for i in range(len(sibling_list)):
            for j in range(i + 1, len(sibling_list)):
                r = _infer_if_missing(
                    sibling_list[i], sibling_list[j], "family",
                    f"{sibling_list[i]} y {sibling_list[j]} son hermanos",
                )
                if r:
                    new_rows.append(r)

    return new_rows
