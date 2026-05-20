"""
Social layer — known_persons y relations en core.db.

Tables (from 002_create_core.sql):
  known_persons  — catalogo base de personas conocidas por Lumi
  relations      — grafo dirigido entre person_ids
  lumi_state     — estado interno dinamico de Lumi (JSON)
  skill_proposals — drafts de evolucion de habilidades

Migrations: 002_create_core.sql
Seeds: seeds/initial_state.sql
"""
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal

from agent.subconscious import core

UTC = timezone.utc

ResolutionStatus = Literal["resolved", "candidate_unconfirmed", "ambiguous", "unknown"]


@dataclass
class PersonMention:
    raw_name: str
    normalized_name: str | None = None
    descriptor: str | None = None
    confidence: float = 1.0


@dataclass
class PersonCandidate:
    person_id: str
    display_name: str
    score: float
    matched_on: str
    relation: dict | None = None
    person: dict | None = None


@dataclass
class PersonResolution:
    status: ResolutionStatus
    mention: PersonMention
    person_id: str | None = None
    display_name: str | None = None
    candidates: list[PersonCandidate] = field(default_factory=list)
    reason: str = ""


def init_core_db():
    """Create core.db and run the full schema (idempotent)."""
    core.init()


# ═══════════════════════════════════════════════════════════════════════════════
# Normalization
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_name(value: str) -> str:
    """Lowercase, strip accents, remove noisy punctuation, collapse spaces."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


# ═══════════════════════════════════════════════════════════════════════════════
# Aliases
# ═══════════════════════════════════════════════════════════════════════════════

def parse_aliases(value: str | list | None) -> list[dict]:
    """Normalize alias input into list-of-dicts format."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(value, list):
        return []

    result = []
    for item in value:
        if isinstance(item, str):
            result.append(build_alias(item))
        elif isinstance(item, dict) and "value" in item:
            if "norm" not in item:
                item["norm"] = normalize_name(item["value"])
            result.append(item)
    return result


def build_alias(value: str, alias_type: str = "alias",
                confirmed: bool = False, confidence: float = 0.6) -> dict:
    return {
        "value": value,
        "norm": normalize_name(value),
        "type": alias_type,
        "confirmed": confirmed,
        "confidence": confidence,
    }


def add_person_alias(person_id: str, alias: str, alias_type: str = "alias",
                     confirmed: bool = False, confidence: float = 0.6) -> dict | None:
    """Add alias to a person, avoiding duplicates by norm."""
    person = get_known_person(person_id)
    if not person:
        return None
    aliases = parse_aliases(person["aliases_json"])
    norm = normalize_name(alias)
    if any(a.get("norm") == norm for a in aliases):
        return person
    aliases.append(build_alias(alias, alias_type, confirmed, confidence))
    return update_known_person(person_id, aliases_json=json.dumps(aliases, ensure_ascii=False))


# ═══════════════════════════════════════════════════════════════════════════════
# Known persons CRUD
# ═══════════════════════════════════════════════════════════════════════════════

def get_known_person(person_id: str) -> dict | None:
    conn = core.get_conn()
    row = conn.execute(
        "SELECT * FROM known_persons WHERE person_id = ?", (person_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def ensure_known_person(
    person_id: str,
    display_name: str | None = None,
    canonical_name: str | None = None,
    aliases: list[dict] | list[str] | None = None,
    interest_score: float = 0.10,
    emotional_tone: str = "neutral",
    status: str = "active",
    notes: str | None = None,
) -> dict:
    """Create or get a known person. Idempotent via INSERT OR IGNORE."""
    existing = get_known_person(person_id)
    if existing:
        return existing

    display = display_name or person_id
    canonical = canonical_name or display
    canonical_norm = normalize_name(canonical)

    if aliases is None:
        aliases = []
    aliases_json = json.dumps(parse_aliases(aliases), ensure_ascii=False)

    conn = core.get_conn()
    conn.execute(
        """INSERT OR IGNORE INTO known_persons
           (person_id, display_name, canonical_name, canonical_name_norm,
            aliases_json, interest_score, emotional_tone, status, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (person_id, display, canonical, canonical_norm,
         aliases_json, interest_score, emotional_tone, status, notes),
    )
    conn.commit()
    conn.close()
    return get_known_person(person_id)


_ALLOWED_UPDATE_FIELDS = {
    "display_name", "canonical_name", "canonical_name_norm",
    "aliases_json", "interest_score", "emotional_tone",
    "status", "last_mentioned", "mention_count", "notes",
}


def update_known_person(person_id: str, **kwargs) -> dict | None:
    """Update known_persons fields. If canonical_name changes, recalculates
    canonical_name_norm unless explicitly provided."""
    person = get_known_person(person_id)
    if not person:
        return None

    updates = {k: v for k, v in kwargs.items() if k in _ALLOWED_UPDATE_FIELDS}
    if not updates:
        return person

    if "canonical_name" in updates and "canonical_name_norm" not in updates:
        updates["canonical_name_norm"] = normalize_name(updates["canonical_name"])

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [person_id]
    conn = core.get_conn()
    conn.execute(
        f"UPDATE known_persons SET {set_clause} WHERE person_id = ?", values
    )
    conn.commit()
    conn.close()
    return get_known_person(person_id)


def increment_person_mention(person_id: str) -> dict | None:
    conn = core.get_conn()
    conn.execute(
        """UPDATE known_persons
           SET mention_count = mention_count + 1,
               last_mentioned = datetime('now')
           WHERE person_id = ?""",
        (person_id,),
    )
    conn.commit()
    conn.close()
    return get_known_person(person_id)


def list_active_known_persons(limit: int = 100) -> list[dict]:
    conn = core.get_conn()
    rows = conn.execute(
        """SELECT * FROM known_persons
           WHERE status != 'forgotten'
           ORDER BY interest_score DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# Relations (relation_policy.md, new schema with relation_label/status/confidence)
# ═══════════════════════════════════════════════════════════════════════════════

def add_relation(from_person_id: str, to_person_id: str,
                 relation_type: str, description: str,
                 relation_label: str | None = None,
                 status: str = "confirmed",
                 confidence: float = 1.0,
                 inferred: int | None = None) -> dict | None:
    """Create or update a directed relation between two person_ids.
    Legacy compat: inferred=1 → status='inferred'."""
    if inferred is not None and inferred == 1:
        status = "inferred"

    if relation_label is None:
        label_map = {
            "family": "related_to",
            "romantic": "partner_of",
            "friendship": "friend_of",
            "professional": "works_with",
            "social": "knows",
            "conflict": "related_to",
            "identity": "related_to",
            "unknown": "related_to",
        }
        relation_label = label_map.get(relation_type, "related_to")

    conn = core.get_conn()
    try:
        conn.execute(
            """INSERT INTO relations
               (from_person_id, to_person_id, relation_type,
                relation_label, description, status, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(from_person_id, to_person_id, relation_label)
               DO UPDATE SET
                   relation_type = excluded.relation_type,
                   description = excluded.description,
                   status = CASE
                       WHEN relations.status = 'confirmed' THEN 'confirmed'
                       ELSE excluded.status
                   END,
                   confidence = excluded.confidence,
                   mention_count = mention_count + 1,
                   last_mentioned = CURRENT_TIMESTAMP,
                   last_updated = CURRENT_TIMESTAMP""",
            (from_person_id, to_person_id, relation_type,
             relation_label, description, status, confidence),
        )
        conn.commit()
        row = conn.execute(
            """SELECT * FROM relations
               WHERE from_person_id = ? AND to_person_id = ?
                 AND relation_label = ?""",
            (from_person_id, to_person_id, relation_label),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.IntegrityError:
        conn.close()
        return None


def get_relations(person_id: str, include_stale: bool = False) -> list[dict]:
    conn = core.get_conn()
    status_filter = "" if include_stale else " AND status != 'stale'"
    rows = conn.execute(
        f"""SELECT * FROM relations
            WHERE (from_person_id = ? OR to_person_id = ?){status_filter}
            ORDER BY mention_count DESC""",
        (person_id, person_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_relation_between(id1: str, id2: str) -> dict | None:
    conn = core.get_conn()
    row = conn.execute(
        """SELECT * FROM relations
           WHERE (from_person_id = ? AND to_person_id = ?)
              OR (from_person_id = ? AND to_person_id = ?)""",
        (id1, id2, id2, id1),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def find_related_persons(
    anchor_person_id: str,
    relation_labels: list[str] | None = None,
    relation_types: list[str] | None = None,
    status: tuple[str, ...] = ("confirmed", "inferred"),
) -> list[dict]:
    """Find persons connected to anchor with relationship details."""
    conn = core.get_conn()

    # Get relations involving anchor
    rows = conn.execute(
        """SELECT * FROM relations
           WHERE (from_person_id = ? OR to_person_id = ?)
           ORDER BY mention_count DESC""",
        (anchor_person_id, anchor_person_id),
    ).fetchall()

    results = []
    for r in rows:
        rd = dict(r)

        if rd["status"] not in status:
            continue
        if relation_labels and rd["relation_label"] not in relation_labels:
            continue
        if relation_types and rd["relation_type"] not in relation_types:
            continue

        connected_id = rd["to_person_id"] if rd["from_person_id"] == anchor_person_id else rd["from_person_id"]

        person_row = conn.execute(
            "SELECT * FROM known_persons WHERE person_id = ?", (connected_id,)
        ).fetchone()
        if person_row:
            pd = dict(person_row)
            results.append({
                "person_id": connected_id,
                "display_name": pd["display_name"],
                "interest_score": pd["interest_score"],
                "emotional_tone": pd["emotional_tone"],
                "person_status": pd["status"],
                "relation": {
                    "relation_id": rd["relation_id"],
                    "relation_type": rd["relation_type"],
                    "relation_label": rd["relation_label"],
                    "description": rd["description"],
                    "status": rd["status"],
                    "confidence": rd["confidence"],
                    "from_person_id": rd["from_person_id"],
                    "to_person_id": rd["to_person_id"],
                },
            })

    conn.close()
    results.sort(key=lambda x: x["interest_score"], reverse=True)
    return results


def delete_relation(relation_id: int):
    conn = core.get_conn()
    conn.execute("DELETE FROM relations WHERE relation_id = ?", (relation_id,))
    conn.commit()
    conn.close()


def increment_relation_mention(from_person_id: str, to_person_id: str):
    conn = core.get_conn()
    conn.execute(
        """UPDATE relations
           SET mention_count = mention_count + 1,
               last_mentioned = datetime('now')
           WHERE from_person_id = ? AND to_person_id = ?""",
        (from_person_id, to_person_id),
    )
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Candidate search & scoring
# ═══════════════════════════════════════════════════════════════════════════════

def _score_canonical_match(canonical_norm: str, query_norm: str,
                           is_single_word: bool) -> float | None:
    if canonical_norm == query_norm:
        return 1.00
    if is_single_word:
        canonical_parts = canonical_norm.split()
        if len(canonical_parts) > 1 and canonical_parts[0] == query_norm:
            return 0.60
    if query_norm in canonical_norm:
        return 0.45
    return None


def _score_alias_match(aliases: list[dict], query_norm: str) -> float | None:
    best = None
    for alias in aliases:
        a_norm = alias.get("norm", "")
        if not a_norm and alias.get("value"):
            a_norm = normalize_name(alias["value"])
        if a_norm != query_norm:
            continue
        if alias.get("confirmed") and alias.get("type") == "full_name":
            score = 0.99
        elif alias.get("confirmed"):
            score = 0.98
        else:
            score = 0.55
        if best is None or score > best:
            best = score
    return best


_FAMILY_ROLES = {
    "mama": "mother_of", "madre": "mother_of", "mami": "mother_of",
    "papa": "father_of", "padre": "father_of", "papi": "father_of",
    "hermano": "sibling_of", "hermana": "sibling_of",
    "hijo": "child_of", "hija": "child_of",
    "tio": "family", "tia": "family",
    "primo": "family", "prima": "family",
    "abuelo": "family", "abuela": "family",
    "esposo": "partner_of", "esposa": "partner_of",
    "novio": "partner_of", "novia": "partner_of",
    "suegro": "family", "suegra": "family",
    "cunado": "family", "cunada": "family",
    "sobrino": "family", "sobrina": "family",
    "nieto": "family", "nieta": "family",
    "padrastro": "family", "madrastra": "family",
}

_WORK_ROLES = {
    "jefe": "boss_of", "jefa": "boss_of",
    "companero": "coworker_of", "colega": "coworker_of",
    "cliente": "works_with", "socio": "works_with",
    "empleado": "boss_of", "empleada": "boss_of",
}

_ALL_ROLES = {**_FAMILY_ROLES, **_WORK_ROLES}


def _score_descriptor_match(relation: dict, descriptor_norm: str) -> float | None:
    rlabel = relation.get("relation_label", "")
    rtype = relation.get("relation_type", "")
    desc_lower = relation.get("description", "").lower()

    if descriptor_norm in _ALL_ROLES:
        expected = _ALL_ROLES[descriptor_norm]
        # Broad match: parent_of covers mother_of/father_of, etc.
        parent_labels = ("mother_of", "father_of", "parent_of")
        child_labels = ("child_of", "son_of", "daughter_of")
        sibling_labels = ("sibling_of", "brother_of", "sister_of")

        if rlabel == expected:
            return 0.96
        if expected in parent_labels and rlabel in parent_labels:
            return 0.96
        if expected in child_labels and rlabel in child_labels:
            return 0.96
        if expected in sibling_labels and rlabel in sibling_labels:
            return 0.96
        if expected == "family" and rtype == "family":
            return 0.88
        if expected == "works_with" and rtype == "professional":
            return 0.88
        if expected == "boss_of" and rlabel == "works_with" and rtype == "professional":
            return 0.88

    if descriptor_norm in desc_lower:
        return 0.96

    return None


def _cnn_like(conn: sqlite3.Connection, query_norm: str) -> list[dict]:
    """Search known_persons by canonical_name_norm substring."""
    rows = conn.execute(
        """SELECT * FROM known_persons
           WHERE canonical_name_norm LIKE ?
              OR canonical_name_norm = ?""",
        (f"%{query_norm}%", query_norm),
    ).fetchall()
    return [dict(r) for r in rows]


def find_person_candidates_by_name(
    raw_name: str,
    anchor_person_id: str | None = None,
    descriptor: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search known_persons for candidates matching a name mention."""
    normalized = normalize_name(raw_name) if raw_name else ""
    desc_norm = normalize_name(descriptor) if descriptor else None
    if not normalized and not (desc_norm and anchor_person_id):
        return []
    is_single_word = len(normalized.split()) == 1 if normalized else False

    conn = core.get_conn()
    candidates = []
    seen_ids: set[str] = set()

    if normalized:
        # 1. Canonical name match
        for person in _cnn_like(conn, normalized):
            score = _score_canonical_match(
                person["canonical_name_norm"], normalized, is_single_word
            )
            if score and score > 0:
                candidates.append({
                    "person_id": person["person_id"],
                    "display_name": person["display_name"],
                    "score": score,
                    "matched_on": "canonical_name",
                    "person": person,
                    "relation": None,
                })

        # 2. Alias match (scan all persons not already matched)
        seen_ids = {c["person_id"] for c in candidates}
        all_rows = conn.execute("SELECT * FROM known_persons").fetchall()
        for row in all_rows:
            person = dict(row)
            if person["person_id"] in seen_ids:
                continue
            aliases = parse_aliases(person["aliases_json"])
            alias_score = _score_alias_match(aliases, normalized)
            if alias_score and alias_score > 0:
                candidates.append({
                    "person_id": person["person_id"],
                    "display_name": person["display_name"],
                    "score": alias_score,
                    "matched_on": "alias",
                    "person": person,
                    "relation": None,
                })
                seen_ids.add(person["person_id"])

    # 3. Descriptor match via relations
    if desc_norm and anchor_person_id:
        rel_rows = conn.execute(
            """SELECT * FROM relations
               WHERE from_person_id = ? OR to_person_id = ?""",
            (anchor_person_id, anchor_person_id),
        ).fetchall()
        for r_row in rel_rows:
            r = dict(r_row)
            related_id = (
                r["to_person_id"]
                if r["from_person_id"] == anchor_person_id
                else r["from_person_id"]
            )
            if related_id in seen_ids:
                continue

            d_score = _score_descriptor_match(r, desc_norm)
            if d_score and d_score > 0:
                person_row = conn.execute(
                    "SELECT * FROM known_persons WHERE person_id = ?",
                    (related_id,),
                ).fetchone()
                if person_row:
                    pd = dict(person_row)
                    candidates.append({
                        "person_id": related_id,
                        "display_name": pd["display_name"],
                        "score": d_score,
                        "matched_on": "descriptor",
                        "person": pd,
                        "relation": r,
                    })
                    seen_ids.add(related_id)

    # 4. Relation boost for weakly matched candidates connected to anchor
    if anchor_person_id:
        for c in candidates:
            if c["relation"] is None:
                rel = get_relation_between(c["person_id"], anchor_person_id)
                if rel:
                    c["relation"] = rel
                    if is_single_word and c["score"] < 0.85:
                        c["score"] = min(c["score"] + 0.15, 0.85)

    conn.close()

    # Sort: score desc → interest_score desc → last_mentioned desc
    candidates.sort(
        key=lambda c: (
            c["score"],
            c.get("person", {}).get("interest_score", 0),
            c.get("person", {}).get("last_mentioned", ""),
        ),
        reverse=True,
    )
    return candidates[:limit]


# ═══════════════════════════════════════════════════════════════════════════════
# Resolution
# ═══════════════════════════════════════════════════════════════════════════════

def resolve_person_mention(
    mention: dict,
    anchor_person_id: str,
    recent_turns: list[dict] | None = None,
) -> dict:
    """Resolve a person mention against known_persons.
    Returns a dict with keys: status, mention, person_id, display_name,
    candidates, reason."""
    raw_name = mention.get("raw_name", "")
    descriptor = mention.get("descriptor")

    candidates_raw = find_person_candidates_by_name(
        raw_name, anchor_person_id, descriptor
    )

    strong = [c for c in candidates_raw if c["score"] >= 0.96]

    if len(strong) == 1:
        return {
            "status": "resolved",
            "mention": mention,
            "person_id": strong[0]["person_id"],
            "display_name": strong[0]["display_name"],
            "candidates": strong,
            "reason": (
                f"Match fuerte ({strong[0]['matched_on']}, "
                f"score={strong[0]['score']:.2f})"
            ),
        }

    if len(candidates_raw) == 1:
        return {
            "status": "candidate_unconfirmed",
            "mention": mention,
            "person_id": candidates_raw[0]["person_id"],
            "display_name": candidates_raw[0]["display_name"],
            "candidates": candidates_raw,
            "reason": (
                f"Candidata unica no confirmada "
                f"(score={candidates_raw[0]['score']:.2f})"
            ),
        }

    if len(candidates_raw) > 1:
        related = [c for c in candidates_raw if c.get("relation")]
        if len(related) == 1:
            return {
                "status": "candidate_unconfirmed",
                "mention": mention,
                "person_id": related[0]["person_id"],
                "display_name": related[0]["display_name"],
                "candidates": related,
                "reason": "Unica candidata relacionada al anchor",
            }
        return {
            "status": "ambiguous",
            "mention": mention,
            "candidates": candidates_raw,
            "reason": f"Multiples candidatas ({len(candidates_raw)})",
        }

    return {
        "status": "unknown",
        "mention": mention,
        "candidates": [],
        "reason": "Sin candidatas en known_persons",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Interest deltas & decay (on known_persons, no session_delta column)
# ═══════════════════════════════════════════════════════════════════════════════

def _recalc_status(person_id: str, score: float):
    """Update status based on interest_score thresholds."""
    conn = core.get_conn()
    row = conn.execute(
        "SELECT status FROM known_persons WHERE person_id = ?", (person_id,)
    ).fetchone()
    if not row or row["status"] == "forgotten":
        conn.close()
        return

    current = row["status"]
    if score < 0 and current != "disliked":
        conn.execute(
            "UPDATE known_persons SET status = 'disliked' WHERE person_id = ?",
            (person_id,),
        )
    elif score >= 0 and current == "disliked":
        conn.execute(
            "UPDATE known_persons SET status = 'active' WHERE person_id = ?",
            (person_id,),
        )
    conn.commit()
    conn.close()


def add_delta(person_id: str, delta: float,
              is_rehabilitation: bool = False) -> dict | None:
    """Apply an interest delta per turn. Jose floor 0.70, non-Jose cap 0.69."""
    person = get_known_person(person_id)
    if not person:
        return None

    is_jose = person_id == "jose"
    current_score = person["interest_score"]

    if is_jose:
        new_score = max(current_score + delta, 0.70)
    else:
        if delta > 0 and is_rehabilitation and current_score < 0:
            effective = min(delta, -current_score)
        elif delta > 0:
            effective = delta
        else:
            effective = delta
        new_score = min(current_score + effective, 0.69)
        new_score = max(new_score, -1.0)

    if abs(new_score - current_score) < 0.0001:
        return person

    conn = core.get_conn()
    conn.execute(
        """UPDATE known_persons
           SET interest_score = ?,
               last_mentioned = datetime('now')
           WHERE person_id = ?""",
        (new_score, person_id),
    )
    conn.commit()
    conn.close()

    _recalc_status(person_id, new_score)
    return get_known_person(person_id)


def commit_session_close():
    """No-op: session_delta column removed. Deltas are applied turn-by-turn."""
    return None


def run_decay():
    """Apply decay to non-Jose active/decaying persons with interest_score >= 0.
    28+ days since last_mentioned → reduce toward 0.10 or mark as decaying."""
    threshold = (datetime.now(UTC) - timedelta(days=28)).isoformat()
    conn = core.get_conn()
    rows = conn.execute(
        """SELECT person_id, interest_score, status
           FROM known_persons
           WHERE person_id != 'jose'
             AND status IN ('active', 'decaying')
             AND interest_score >= 0
             AND last_mentioned < ?""",
        (threshold,),
    ).fetchall()

    for r in rows:
        person_id = r["person_id"]
        current = r["interest_score"]
        new_score = max(current - 0.02, 0.10)
        new_status = "decaying" if new_score <= 0.15 else r["status"]

        conn.execute(
            """UPDATE known_persons
               SET interest_score = ?, status = ?
               WHERE person_id = ?""",
            (new_score, new_status, person_id),
        )

    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Family inference (backward compat — calls add_relation with inferred→status)
# ═══════════════════════════════════════════════════════════════════════════════

def infer_family_relations() -> list[dict]:
    """Apply the 4 inference rules from relation_policy.md (direct family only).
    Inserts inferred relations with status='inferred'."""
    new_rows = []

    def _infer_if_missing(from_id, to_id, rtype, desc, label=None):
        existing = get_relation_between(from_id, to_id)
        if existing:
            return None
        r = add_relation(from_id, to_id, rtype, desc,
                         relation_label=label, status="inferred")
        if r:
            new_rows.append(r)
        return r

    conn = core.get_conn()
    families = conn.execute(
        """SELECT from_person_id, to_person_id, relation_label, description
           FROM relations WHERE relation_type = 'family'"""
    ).fetchall()
    conn.close()

    is_parent_of_jose = set()
    is_sibling_of_jose = set()

    for r in families:
        fid, tid, label, desc = (
            r["from_person_id"], r["to_person_id"],
            r["relation_label"], r["description"]
        )
        if tid == "jose":
            if label in ("mother_of", "father_of", "parent_of"):
                is_parent_of_jose.add(fid)
            if label in ("sibling_of", "brother_of", "sister_of"):
                is_sibling_of_jose.add(fid)
        if fid == "jose":
            if label in ("child_of",):
                is_parent_of_jose.add(tid)
            if label in ("sibling_of", "brother_of", "sister_of"):
                is_sibling_of_jose.add(tid)

    # 1. Parents are partners
    parent_list = list(is_parent_of_jose)
    if len(parent_list) >= 2:
        for i in range(len(parent_list)):
            for j in range(i + 1, len(parent_list)):
                _infer_if_missing(
                    parent_list[i], parent_list[j], "romantic",
                    f"{parent_list[i]} y {parent_list[j]} son los padres de Jose",
                    label="partner_of",
                )

    # 2. Parent–sibling = family
    for parent in is_parent_of_jose:
        for sibling in is_sibling_of_jose:
            _infer_if_missing(
                parent, sibling, "family",
                f"{parent} es padre/madre de {sibling}",
                label="parent_of",
            )

    # 3. Siblings with each other
    sibling_list = list(is_sibling_of_jose)
    if len(sibling_list) >= 2:
        for i in range(len(sibling_list)):
            for j in range(i + 1, len(sibling_list)):
                _infer_if_missing(
                    sibling_list[i], sibling_list[j], "family",
                    f"{sibling_list[i]} y {sibling_list[j]} son hermanos",
                    label="sibling_of",
                )

    return new_rows


# ═══════════════════════════════════════════════════════════════════════════════
# Legacy wrappers — preserved for working_memory.py and app.py compatibility
# ═══════════════════════════════════════════════════════════════════════════════

def create_person_interest(person_id: str, is_jose: int = 0,
                           interest_score: float = 0.10) -> dict:
    """Legacy wrapper. Ensures the person exists in known_persons."""
    display_name = "Jose Barco" if person_id == "jose" else person_id
    score = 1.00 if person_id == "jose" else interest_score
    return ensure_known_person(
        person_id=person_id,
        display_name=display_name,
        canonical_name=display_name,
        interest_score=score,
        emotional_tone="positive" if person_id == "jose" else "neutral",
    )


def get_user_information(user_id: str) -> dict:
    """Legacy wrapper. Returns {profile: None, interest: known_person}."""
    return {
        "profile": None,
        "interest": get_known_person(user_id),
    }


def set_user_information(user_id: str, profile: dict = None,
                         interest: dict = None):
    """Legacy wrapper. Ensures person exists, applies interest fields.
    profile is ignored (no user_profiles table)."""
    if get_known_person(user_id) is None:
        ensure_known_person(user_id)
    if interest:
        update_known_person(user_id, **interest)


def find_user_id_by_name(name: str) -> str | None:
    """Legacy wrapper. Returns person_id only for strong match (score >= 0.96)."""
    candidates = find_person_candidates_by_name(name)
    strong = [c for c in candidates if c["score"] >= 0.96]
    return strong[0]["person_id"] if len(strong) == 1 else None
