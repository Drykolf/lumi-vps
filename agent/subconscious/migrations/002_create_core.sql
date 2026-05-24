-- LUMI core.db
-- This is the SOURCE OF TRUTH for:
--   * Person interest tracking (score, tone, status)
--   * User structured profiles (name, location, static data)
--   * Relations between third parties
--   * Lumi's internal dynamic state
--   * Pending skill proposals (skill_evolution)
--
-- Mem0 (pgvector) stores the SEMANTIC MEMORIES about each person,
-- linked to this DB via metadata.person_id.
-- Conversation history stays in its own SQLite (traces.db) — separate concern.

PRAGMA foreign_keys = ON;

-- ============================================================
-- PERSON_INTEREST — Lumi's emotional calculus toward each person
-- ============================================================
-- Names live in Mem0 (semantic facts) or user_profiles (for Jose).
-- This table tracks only the relationship dynamic.


CREATE TABLE IF NOT EXISTS known_persons (
    person_id TEXT PRIMARY KEY,

    display_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    canonical_name_norm TEXT NOT NULL,

    aliases_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(aliases_json)),

    interest_score REAL NOT NULL DEFAULT 0.10,
    emotional_tone TEXT NOT NULL DEFAULT 'neutral',
    status TEXT NOT NULL DEFAULT 'active',

    first_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_mentioned DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mention_count INTEGER NOT NULL DEFAULT 1,

    -- Nightly step 7 (cleanup_memory_tiers): anchor for grace-period deletion
    -- of persons whose status flipped to 'forgotten'. Set when status changes.
    forgotten_at DATETIME,

    notes TEXT,

    CHECK (interest_score >= -1.0 AND interest_score <= 1.0),
    CHECK (emotional_tone IN ('positive', 'neutral', 'negative', 'complex')),
    CHECK (status IN ('active', 'provisional', 'decaying', 'forgotten', 'disliked', 'unknown'))
);

CREATE INDEX IF NOT EXISTS idx_known_persons_canonical_name_norm
    ON known_persons(canonical_name_norm);

CREATE INDEX IF NOT EXISTS idx_known_persons_interest_score
    ON known_persons(interest_score DESC);

CREATE INDEX IF NOT EXISTS idx_known_persons_status
    ON known_persons(status);

CREATE INDEX IF NOT EXISTS idx_known_persons_last_mentioned
    ON known_persons(last_mentioned DESC);

CREATE TABLE IF NOT EXISTS relations (
    relation_id INTEGER PRIMARY KEY AUTOINCREMENT,

    from_person_id TEXT NOT NULL,
    to_person_id TEXT NOT NULL,

    relation_type TEXT NOT NULL DEFAULT 'unknown',
    relation_label TEXT NOT NULL,
    description TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'confirmed',
    confidence REAL NOT NULL DEFAULT 1.0,

    first_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_mentioned DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mention_count INTEGER NOT NULL DEFAULT 1,

    CHECK (from_person_id != to_person_id),
    CHECK (relation_type IN (
        'family',
        'romantic',
        'friendship',
        'professional',
        'social',
        'conflict',
        'identity',
        'unknown'
    )),
    CHECK (status IN (
        'confirmed',
        'inferred',
        'disputed',
        'rejected',
        'stale',
        'unknown'
    )),
    CHECK (confidence >= 0.0 AND confidence <= 1.0),

    UNIQUE (from_person_id, to_person_id, relation_label),

    FOREIGN KEY (from_person_id)
        REFERENCES known_persons(person_id)
        ON DELETE CASCADE,

    FOREIGN KEY (to_person_id)
        REFERENCES known_persons(person_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_relations_from_person_id
    ON relations(from_person_id);

CREATE INDEX IF NOT EXISTS idx_relations_to_person_id
    ON relations(to_person_id);

CREATE INDEX IF NOT EXISTS idx_relations_pair
    ON relations(from_person_id, to_person_id);

CREATE INDEX IF NOT EXISTS idx_relations_relation_label
    ON relations(relation_label);

CREATE INDEX IF NOT EXISTS idx_relations_relation_type
    ON relations(relation_type);

CREATE INDEX IF NOT EXISTS idx_relations_status
    ON relations(status);

CREATE INDEX IF NOT EXISTS idx_relations_last_mentioned
    ON relations(last_mentioned DESC);

CREATE TRIGGER IF NOT EXISTS trg_relations_last_updated
AFTER UPDATE ON relations
FOR EACH ROW
BEGIN
    UPDATE relations
    SET last_updated = CURRENT_TIMESTAMP
    WHERE relation_id = OLD.relation_id;
END;

-- ============================================================
-- PERSON_IDENTIFIERS — messaging-platform handles for known persons
-- ============================================================
-- One row per (person_id, platform, identifier). Platform 'whatsapp' stores
-- the E.164 phone number (same number also reachable via SMS/voice — the
-- inbound transport is recorded per-request as ChatRequest.channel).
-- New platforms (telegram, signal, ...) are added by extending the CHECK.
CREATE TABLE IF NOT EXISTS person_identifiers (
    identifier_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL,

    platform TEXT NOT NULL,
    identifier TEXT NOT NULL,

    verified INTEGER NOT NULL DEFAULT 0,
    notes TEXT,

    first_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (platform IN ('whatsapp', 'discord')),
    CHECK (verified IN (0, 1)),
    UNIQUE (platform, identifier),

    FOREIGN KEY (person_id)
        REFERENCES known_persons(person_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_person_identifiers_person_id
    ON person_identifiers(person_id);

CREATE INDEX IF NOT EXISTS idx_person_identifiers_lookup
    ON person_identifiers(platform, identifier);

CREATE TRIGGER IF NOT EXISTS trg_person_identifiers_updated_at
AFTER UPDATE ON person_identifiers
FOR EACH ROW
BEGIN
    UPDATE person_identifiers
    SET updated_at = CURRENT_TIMESTAMP
    WHERE identifier_id = OLD.identifier_id;
END;

-- ============================================================
-- LUMI_STATE — Lumi's own dynamic internal state
-- ============================================================
-- Single-row key/value to keep the schema flexible.
-- Canonical key: 'internal_state' → JSON blob defined in mood_policy.md
-- Schema per mood_policy.md §509-588.
-- Canonical key: 'mood_state' → JSON blob with all mood fields.
-- Other keys reserved for future use (e.g. 'last_introspection').
CREATE TABLE IF NOT EXISTS lumi_state (
    key TEXT PRIMARY KEY,

    data TEXT NOT NULL CHECK (json_valid(data)),

    -- Generated virtual columns for frequently queried mood fields
    mood_valence REAL
        GENERATED ALWAYS AS (json_extract(data, '$.mood_valence')) VIRTUAL,

    mood_energy REAL
        GENERATED ALWAYS AS (json_extract(data, '$.mood_energy')) VIRTUAL,

    irritation REAL
        GENERATED ALWAYS AS (json_extract(data, '$.irritation')) VIRTUAL,

    focus_level REAL
        GENERATED ALWAYS AS (json_extract(data, '$.focus_level')) VIRTUAL,

    presence_need REAL
        GENERATED ALWAYS AS (json_extract(data, '$.presence_need')) VIRTUAL,

    state_label TEXT
        GENERATED ALWAYS AS (json_extract(data, '$.state_label')) VIRTUAL,

    emotional_honesty_mode INTEGER
        GENERATED ALWAYS AS (json_extract(data, '$.emotional_honesty_mode')) VIRTUAL,

    negative_load REAL
        GENERATED ALWAYS AS (json_extract(data, '$.negative_load')) VIRTUAL,

    last_interaction_at TEXT
        GENERATED ALWAYS AS (json_extract(data, '$.last_interaction_at')) VIRTUAL,

    last_meaningful_interaction_at TEXT
        GENERATED ALWAYS AS (json_extract(data, '$.last_meaningful_interaction_at')) VIRTUAL,

    last_day_reset TEXT
        GENERATED ALWAYS AS (json_extract(data, '$.last_day_reset')) VIRTUAL,

    last_updated TEXT
        GENERATED ALWAYS AS (json_extract(data, '$.last_updated')) VIRTUAL,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (key <> ''),
    CHECK (mood_valence IS NULL OR (mood_valence >= -1.0 AND mood_valence <= 1.0)),
    CHECK (mood_energy IS NULL OR (mood_energy >= 0.0 AND mood_energy <= 1.0)),
    CHECK (irritation IS NULL OR (irritation >= 0.0 AND irritation <= 1.0)),
    CHECK (focus_level IS NULL OR (focus_level >= 0.0 AND focus_level <= 1.0)),
    CHECK (presence_need IS NULL OR (presence_need >= 0.0 AND presence_need <= 1.0))
);

CREATE INDEX IF NOT EXISTS idx_lumi_state_label ON lumi_state(state_label);
CREATE INDEX IF NOT EXISTS idx_lumi_state_last_updated ON lumi_state(last_updated);

CREATE TRIGGER IF NOT EXISTS trg_lumi_state_updated_at
AFTER UPDATE ON lumi_state
FOR EACH ROW
BEGIN
    UPDATE lumi_state
    SET updated_at = datetime('now')
    WHERE key = OLD.key;
END;

-- ============================================================
-- SKILL_PROPOSALS — auto-learning candidates awaiting review
-- ============================================================
-- See skill_evolution.md. Lumi never auto-loads a skill from this table.
-- Jose reviews drafts manually; on approval the file is moved out of _drafts/.
CREATE TABLE IF NOT EXISTS skill_proposals (
    proposal_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    proposed_name   TEXT    NOT NULL,                    -- snake_case skill name
    pattern_count   INTEGER NOT NULL,                    -- occurrences observed
    pattern_window_days INTEGER NOT NULL,                -- detection window
    sample_queries  TEXT    NOT NULL,                    -- JSON array of triggering messages (max 5)
    rationale       TEXT    NOT NULL,                    -- Lumi's one-paragraph reasoning, in Spanish
    draft_path      TEXT    NOT NULL,                    -- e.g. "src/skills/_drafts/research_v2.md"
    parent_skill    TEXT,                                -- if this is an edit to existing skill
    status          TEXT    NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | superseded
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at     DATETIME,
    review_notes    TEXT,                                -- Jose's notes on rejection or edits
    CHECK (status IN ('pending','approved','rejected','superseded'))
);

CREATE INDEX IF NOT EXISTS idx_skill_proposals_status ON skill_proposals(status);

-- ============================================================
-- HEARTBEAT_STATE — scheduler job registry and status
-- ============================================================
CREATE TABLE IF NOT EXISTS heartbeat_state (
    task_name TEXT PRIMARY KEY,
    last_run_at TEXT,
    last_success_at TEXT,
    next_run_at TEXT,
    status TEXT NOT NULL DEFAULT 'never',
    last_error TEXT,
    run_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- One-time data backfill for negative_load (idempotent)
-- ============================================================
UPDATE lumi_state
SET data = json_set(data, '$.negative_load', 0.0)
WHERE key = 'mood_state'
  AND json_extract(data, '$.negative_load') IS NULL;
