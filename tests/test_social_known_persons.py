"""
Tests for social.py — known_persons, relations, aliases, resolution.
No LLM, no Mem0. Pure unit tests against core.db schema.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure agent package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("MEM0_ADMIN_API_KEY", "test")

# Force fresh core.db for tests
os.environ["LUMI_TEST_DB"] = "1"


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch, tmp_path):
    """Redirect core.db and traces.db to temp dir, run init per test."""
    core_db = tmp_path / "core.db"
    monkeypatch.setattr(
        "agent.subconscious.repositories.core.CoreRepository.db_path",
        core_db,
    )
    from agent.subconscious.repositories.core import CoreRepository

    class TestCoreRepo(CoreRepository):
        def __init__(self):
            self.db_path = core_db
            self.migration_path = (
                Path(__file__).parent.parent
                / "agent"
                / "subconscious"
                / "migrations"
                / "002_create_core.sql"
            )
            self.seeds_path = (
                Path(__file__).parent.parent
                / "agent"
                / "subconscious"
                / "seeds"
                / "initial_state.sql"
            )

    repo = TestCoreRepo()
    monkeypatch.setattr("agent.subconscious.core", repo)
    repo.init()
    return repo


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Seed Jose
# ═══════════════════════════════════════════════════════════════════════════════

def test_jose_seeded(fresh_db):
    from agent.memory.mindstream.social import get_known_person

    jose = get_known_person("jose")
    assert jose is not None
    assert jose["display_name"] == "Jose Barco"
    assert jose["interest_score"] >= 0.70
    assert jose["emotional_tone"] == "positive"
    assert jose["status"] == "active"


def test_jose_seed_aliases(fresh_db):
    from agent.memory.mindstream.social import get_known_person, parse_aliases

    jose = get_known_person("jose")
    aliases = parse_aliases(jose["aliases_json"])
    assert len(aliases) == 2
    names = {a["norm"] for a in aliases}
    assert "jose barco" in names
    assert "jose" in names


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Alias exacto fuerte
# ═══════════════════════════════════════════════════════════════════════════════

def test_alias_exact_resolves(fresh_db):
    from agent.memory.mindstream.social import (
        ensure_known_person,
        add_person_alias,
        find_person_candidates_by_name,
        resolve_person_mention,
    )

    ensure_known_person(
        "gloria1",
        display_name="Gloria Barco",
        canonical_name="Gloria Barco",
        interest_score=0.80,
    )
    add_person_alias("gloria1", "Gloria Barco", "full_name", confirmed=True, confidence=1.0)

    candidates = find_person_candidates_by_name("Gloria Barco")
    assert len(candidates) >= 1
    assert candidates[0]["person_id"] == "gloria1"
    assert candidates[0]["score"] >= 0.96

    resolution = resolve_person_mention(
        {"raw_name": "Gloria Barco"}, anchor_person_id="jose"
    )
    assert resolution["status"] == "resolved"
    assert resolution["person_id"] == "gloria1"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Primer nombre debil con una candidata relacionada → candidate_unconfirmed
# ═══════════════════════════════════════════════════════════════════════════════

def test_single_word_related_candidate_unconfirmed(fresh_db):
    from agent.memory.mindstream.social import (
        ensure_known_person,
        add_relation,
        resolve_person_mention,
    )

    ensure_known_person(
        "gloria1",
        display_name="Gloria Barco",
        canonical_name="Gloria Barco",
    )
    add_relation(
        "gloria1", "jose", "family",
        "Gloria es la mama de Jose",
        relation_label="mother_of",
        status="confirmed",
    )

    resolution = resolve_person_mention(
        {"raw_name": "Gloria"}, anchor_person_id="jose"
    )
    assert resolution["status"] == "candidate_unconfirmed"
    assert resolution["person_id"] == "gloria1"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Primer nombre con varias candidatas → ambiguous
# ═══════════════════════════════════════════════════════════════════════════════

def test_multiple_candidates_ambiguous(fresh_db):
    from agent.memory.mindstream.social import (
        ensure_known_person,
        add_relation,
        resolve_person_mention,
    )

    ensure_known_person(
        "gloria1",
        display_name="Gloria Barco",
        canonical_name="Gloria Barco",
    )
    ensure_known_person(
        "gloria2",
        display_name="Gloria Perez",
        canonical_name="Gloria Perez",
    )
    add_relation("gloria1", "jose", "family",
                 "Gloria es la mama de Jose",
                 relation_label="mother_of")
    add_relation("gloria2", "jose", "professional",
                 "Gloria trabaja con Jose",
                 relation_label="coworker_of")

    resolution = resolve_person_mention(
        {"raw_name": "Gloria"}, anchor_person_id="jose"
    )
    assert resolution["status"] == "ambiguous"
    assert len(resolution["candidates"]) >= 2


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Descriptor relacional "mi mama" → resolved
# ═══════════════════════════════════════════════════════════════════════════════

def test_descriptor_resolves(fresh_db):
    from agent.memory.mindstream.social import (
        ensure_known_person,
        add_relation,
        resolve_person_mention,
    )

    ensure_known_person(
        "gloria1",
        display_name="Gloria Barco",
        canonical_name="Gloria Barco",
    )
    add_relation(
        "gloria1", "jose", "family",
        "Gloria es la mama de Jose",
        relation_label="mother_of",
        status="confirmed",
    )

    resolution = resolve_person_mention(
        {"raw_name": "", "descriptor": "mi mama"}, anchor_person_id="jose"
    )
    # Descriptor match + no raw_name → should find via relation
    candidates = resolution.get("candidates", [])
    # With empty raw_name it won't match canonical, but the descriptor
    # should pick up the relation
    assert resolution["status"] in ("resolved", "candidate_unconfirmed")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Unknown — sin candidatos
# ═══════════════════════════════════════════════════════════════════════════════

def test_unknown_person(fresh_db):
    from agent.memory.mindstream.social import (
        find_person_candidates_by_name,
        resolve_person_mention,
    )

    candidates = find_person_candidates_by_name("Marcela", anchor_person_id="jose")
    assert len(candidates) == 0

    resolution = resolve_person_mention(
        {"raw_name": "Marcela"}, anchor_person_id="jose"
    )
    assert resolution["status"] == "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Legacy wrappers
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_user_information_returns_known_person(fresh_db):
    from agent.memory.mindstream.social import get_user_information

    info = get_user_information("jose")
    assert info["profile"] is None
    assert info["interest"]["person_id"] == "jose"
    assert info["interest"]["display_name"] == "Jose Barco"


def test_create_person_interest_jose(fresh_db):
    from agent.memory.mindstream.social import get_known_person, create_person_interest

    # Jose should already exist from seed; call is idempotent
    person = create_person_interest("jose", is_jose=1, interest_score=1.0)
    assert person["person_id"] == "jose"
    assert person["interest_score"] >= 1.0


def test_create_person_interest_new(fresh_db):
    from agent.memory.mindstream.social import get_known_person, create_person_interest

    person = create_person_interest("test_user")
    assert person["person_id"] == "test_user"
    assert person["interest_score"] == 0.10
    assert person["emotional_tone"] == "neutral"


def test_set_user_information(fresh_db):
    from agent.memory.mindstream.social import (
        get_known_person,
        set_user_information,
    )

    set_user_information("new_user",
                         interest={"emotional_tone": "positive",
                                   "interest_score": 0.25})
    person = get_known_person("new_user")
    assert person is not None
    assert person["emotional_tone"] == "positive"
    assert person["interest_score"] == 0.25


def test_find_user_id_by_name(fresh_db):
    from agent.memory.mindstream.social import find_user_id_by_name

    # "Jose Barco" should match canonically with score >= 0.96
    result = find_user_id_by_name("Jose Barco")
    assert result == "jose"


def test_find_user_id_by_name_unknown(fresh_db):
    from agent.memory.mindstream.social import find_user_id_by_name

    result = find_user_id_by_name("Nobody")
    assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Working memory compatibility smoke test (import must succeed)
# ═══════════════════════════════════════════════════════════════════════════════

def test_working_memory_imports_ok():
    from agent.cognition.working_memory import build_messages
    assert callable(build_messages)


def test_memory_init_imports_all_ok(fresh_db):
    import agent.memory
    assert hasattr(agent.memory, "get_user_information")
    assert hasattr(agent.memory, "set_user_information")
    assert hasattr(agent.memory, "create_person_interest")
    assert hasattr(agent.memory, "add_delta")
    assert hasattr(agent.memory, "commit_session_close")
    assert hasattr(agent.memory, "run_decay")
    assert hasattr(agent.memory, "get_relations")
    assert hasattr(agent.memory, "add_relation")
    assert hasattr(agent.memory, "infer_family_relations")
    assert hasattr(agent.memory, "find_user_id_by_name")
    # New functions
    assert hasattr(agent.memory, "get_known_person")
    assert hasattr(agent.memory, "ensure_known_person")
    assert hasattr(agent.memory, "resolve_person_mention")
    assert hasattr(agent.memory, "find_person_candidates_by_name")


# ═══════════════════════════════════════════════════════════════════════════════
# Additional: CRUD, aliases, relations
# ═══════════════════════════════════════════════════════════════════════════════

def test_ensure_known_person_creates(fresh_db):
    from agent.memory.mindstream.social import get_known_person, ensure_known_person

    p = ensure_known_person("carlos1", display_name="Carlos Ruiz",
                            interest_score=0.30)
    assert p["person_id"] == "carlos1"
    assert p["display_name"] == "Carlos Ruiz"
    assert p["canonical_name_norm"] == "carlos ruiz"
    assert p["interest_score"] == 0.30
    assert p["status"] == "active"


def test_update_known_person(fresh_db):
    from agent.memory.mindstream.social import get_known_person, update_known_person

    update_known_person("jose", interest_score=0.95, notes="Updated")
    jose = get_known_person("jose")
    assert jose["interest_score"] == 0.95
    assert jose["notes"] == "Updated"


def test_list_active_excludes_forgotten(fresh_db):
    from agent.memory.mindstream.social import (
        ensure_known_person,
        update_known_person,
        list_active_known_persons,
    )

    ensure_known_person("forgotten1")
    update_known_person("forgotten1", status="forgotten")

    active = list_active_known_persons()
    ids = {p["person_id"] for p in active}
    assert "jose" in ids
    assert "forgotten1" not in ids


def test_normalize_name(fresh_db):
    from agent.memory.mindstream.social import normalize_name

    assert normalize_name("José Barco") == "jose barco"
    assert normalize_name("  Tía   Gloria ") == "tia gloria"
    assert normalize_name("Gloria-Barco") == "gloria barco"
    assert normalize_name("") == ""


def test_parse_aliases_string_json(fresh_db):
    from agent.memory.mindstream.social import parse_aliases

    result = parse_aliases('["Gloria", "Tia Gloria"]')
    assert len(result) == 2
    assert result[0]["norm"] == "gloria"
    assert result[1]["norm"] == "tia gloria"


def test_add_person_alias(fresh_db):
    from agent.memory.mindstream.social import (
        get_known_person,
        ensure_known_person,
        add_person_alias,
        parse_aliases,
    )

    ensure_known_person("carlos1", display_name="Carlos", canonical_name="Carlos")
    add_person_alias("carlos1", "Carlitos", "nickname", confirmed=True, confidence=0.9)

    person = get_known_person("carlos1")
    aliases = parse_aliases(person["aliases_json"])
    assert any(a["norm"] == "carlitos" for a in aliases)


def test_add_relation_new_schema(fresh_db):
    from agent.memory.mindstream.social import (
        add_relation,
        get_relation_between,
        get_relations,
    )

    r = add_relation("jose", "jose", "family", "test", relation_label="parent_of")
    assert r is None  # CHECK: from != to

    r = add_relation(
        "jose", "unknown_person", "family", "should fail",
        relation_label="parent_of",
    )
    assert r is None  # FK constraint: to_person_id must exist

    # Valid relation (jose exists from seed)
    r = add_relation(
        "jose", "jose", "friendship", "test desc",
        relation_label="friend_of",
    )
    assert r is None  # still fails because CHECK from != to

    # Let me test with a valid scenario: need another person
    from agent.memory.mindstream.social import ensure_known_person

    ensure_known_person("test1")
    r = add_relation(
        "jose", "test1", "friendship",
        "Jose y test1 son amigos",
        relation_label="friend_of",
        status="confirmed",
    )
    assert r is not None
    assert r["relation_label"] == "friend_of"
    assert r["relation_type"] == "friendship"
    assert r["status"] == "confirmed"
    assert r["confidence"] == 1.0

    # Duplicate upsert increments mention_count
    r2 = add_relation(
        "jose", "test1", "friendship",
        "Updated desc",
        relation_label="friend_of",
        status="inferred",
    )
    assert r2 is not None
    assert r2["mention_count"] >= 2
    assert r2["description"] == "Updated desc"
    # Status stays confirmed on upsert
    assert r2["status"] == "confirmed"

    # Verify get_relations
    rels = get_relations("jose")
    assert len(rels) >= 1


def test_add_relation_legacy_inferred(fresh_db):
    from agent.memory.mindstream.social import (
        ensure_known_person,
        add_relation,
    )

    ensure_known_person("test2")
    r = add_relation(
        "jose", "test2", "family", "inferred relation",
        inferred=1,
    )
    assert r is not None
    assert r["status"] == "inferred"


def test_find_related_persons(fresh_db):
    from agent.memory.mindstream.social import (
        ensure_known_person,
        add_relation,
        find_related_persons,
    )

    ensure_known_person("alice", display_name="Alice", interest_score=0.70)
    ensure_known_person("bob", display_name="Bob", interest_score=0.50)

    add_relation("jose", "alice", "friendship", "Jose y Alice son amigos",
                 relation_label="friend_of")
    add_relation("bob", "jose", "professional", "Bob trabaja con Jose",
                 relation_label="coworker_of")

    related = find_related_persons("jose")
    assert len(related) == 2
    assert related[0]["person_id"] == "alice"  # higher interest_score first
    assert related[1]["person_id"] == "bob"


def test_increment_person_mention(fresh_db):
    from agent.memory.mindstream.social import (
        get_known_person,
        increment_person_mention,
    )

    before = get_known_person("jose")
    mc_before = before["mention_count"]

    after = increment_person_mention("jose")
    assert after["mention_count"] == mc_before + 1


def test_add_delta_jose_floor(fresh_db):
    from agent.memory.mindstream.social import add_delta, get_known_person

    # Jose starts at 1.00. Trying to go below 0.70 should floor.
    add_delta("jose", -0.50)
    jose = get_known_person("jose")
    assert jose["interest_score"] >= 0.70


def test_add_delta_non_jose_cap(fresh_db):
    from agent.memory.mindstream.social import (
        ensure_known_person,
        add_delta,
        get_known_person,
    )

    ensure_known_person("nonjose", interest_score=0.68)
    add_delta("nonjose", 0.05)
    person = get_known_person("nonjose")
    assert person["interest_score"] <= 0.69


def test_run_decay(fresh_db):
    from agent.memory.mindstream.social import (
        ensure_known_person,
        update_known_person,
        run_decay,
        get_known_person,
    )
    from datetime import timedelta

    ensure_known_person("decay_target", display_name="Decay", interest_score=0.50)
    # Set last_mentioned to 30 days ago
    old_date = (__import__("datetime").datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    update_known_person("decay_target", last_mentioned=old_date, status="active")

    run_decay()
    person = get_known_person("decay_target")
    assert person["interest_score"] < 0.50


def test_infer_family_relations(fresh_db):
    from agent.memory.mindstream.social import (
        ensure_known_person,
        add_relation,
        infer_family_relations,
    )

    ensure_known_person("gloria1", display_name="Gloria Barco", canonical_name="Gloria Barco")
    ensure_known_person("juan1", display_name="Juan Barco", canonical_name="Juan Barco")
    ensure_known_person("carlos_bro", display_name="Carlos Barco", canonical_name="Carlos Barco")

    add_relation("gloria1", "jose", "family", "Gloria es la mama de Jose",
                 relation_label="mother_of", status="confirmed")
    add_relation("juan1", "jose", "family", "Juan es el papa de Jose",
                 relation_label="father_of", status="confirmed")
    add_relation("carlos_bro", "jose", "family", "Carlos es hermano de Jose",
                 relation_label="sibling_of", status="confirmed")

    new_relations = infer_family_relations()
    # Should infer: gloria1 partner_of juan1, gloria1 parent_of carlos_bro,
    # juan1 parent_of carlos_bro
    assert len(new_relations) >= 3


def test_commit_session_close_noop(fresh_db):
    from agent.memory.mindstream.social import commit_session_close

    result = commit_session_close()
    assert result is None
