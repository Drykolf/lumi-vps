"""
Core state database — persons, relations, lumi_state, skill_proposals.
Implements interest_policy.md and relation_policy.md storage layer.

Tables (from 00_schema_sqlite.sql):
  persons      — registry of every named entity Lumi knows
  relations    — directed connections between third parties
  lumi_state   — Lumi's own dynamic internal state (JSON)
  skill_proposals — pending skill evolution drafts

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
# Person registry
# ═══════════════════════════════════════════════════════════════════════════════

def get_person(person_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM persons WHERE person_id = ?", (person_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def find_person_by_name(name: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM persons WHERE canonical_name = ?", (name,)
    ).fetchone()
    if row:
        conn.close()
        return dict(row)

    rows = conn.execute(
        "SELECT * FROM persons WHERE aliases IS NOT NULL"
    ).fetchall()
    conn.close()

    for r in rows:
        try:
            aliases = json.loads(r["aliases"])
            if name in aliases:
                return dict(r)
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def create_person(person_id: str, canonical_name: str,
                  aliases: list[str] | None = None,
                  is_jose: int = 0,
                  interest_score: float = 0.10) -> dict:
    conn = _conn()
    aliases_json = json.dumps(aliases, ensure_ascii=False) if aliases else None
    conn.execute(
        """INSERT INTO persons (person_id, canonical_name, aliases, is_jose, interest_score)
           VALUES (?, ?, ?, ?, ?)""",
        (person_id, canonical_name, aliases_json, is_jose, interest_score),
    )
    conn.commit()
    conn.close()
    return get_person(person_id)


def update_person(person_id: str, **kwargs) -> dict | None:
    allowed = {"canonical_name", "interest_score", "emotional_tone",
               "status", "notes", "session_delta", "aliases"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_person(person_id)

    # Serialize aliases if passed as a list
    if "aliases" in updates and isinstance(updates["aliases"], list):
        updates["aliases"] = json.dumps(updates["aliases"], ensure_ascii=False)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [person_id]
    conn = _conn()
    conn.execute(
        f"UPDATE persons SET {set_clause} WHERE person_id = ?", values
    )
    conn.commit()
    conn.close()
    return get_person(person_id)


def increment_mention(person_id: str):
    conn = _conn()
    conn.execute(
        """UPDATE persons
           SET mention_count = mention_count + 1,
               last_mentioned = datetime('now')
           WHERE person_id = ?""",
        (person_id,),
    )
    conn.commit()
    conn.close()


def list_active_persons() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM persons WHERE status != 'forgotten' ORDER BY interest_score DESC"
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
    person = get_person(person_id)
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
        """UPDATE persons
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
        "SELECT status FROM persons WHERE person_id = ?", (person_id,)
    ).fetchone()
    if not row or row["status"] == "forgotten":
        conn.close()
        return

    current = row["status"]
    if score < 0 and current != "disliked":
        conn.execute(
            "UPDATE persons SET status = 'disliked' WHERE person_id = ?",
            (person_id,),
        )
    elif score >= 0 and current == "disliked":
        conn.execute(
            "UPDATE persons SET status = 'active' WHERE person_id = ?",
            (person_id,),
        )
    conn.commit()
    conn.close()


def commit_session_close():
    """Reset all session_delta values to 0. Called at session end.
    interest_scores have already been updated turn-by-turn."""
    conn = _conn()
    conn.execute("UPDATE persons SET session_delta = 0.0 WHERE session_delta != 0.0")
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

    # Build lookup: person_id -> {role: True}
    is_parent_of_jose = set()  # person_ids that are parents of Jose
    is_sibling_of_jose = set()  # person_ids that are siblings of Jose

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

    # Rule 1: parents of Jose → romantic between them
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

    # Rules 2-4: parents ↔ siblings
    for parent in is_parent_of_jose:
        for sibling in is_sibling_of_jose:
            r = _infer_if_missing(
                parent, sibling, "family",
                f"{parent} es padre/madre de {sibling}",
            )
            if r:
                new_rows.append(r)

    # Rule: siblings are siblings of each other
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
