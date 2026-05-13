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
CREATE TABLE IF NOT EXISTS person_interest (
    person_id        TEXT PRIMARY KEY,                    -- e.g. "jose", "gloria1", "carlos_jefe"
    is_jose          INTEGER NOT NULL DEFAULT 0,          -- 1 only for the row where person_id="jose"
    interest_score   REAL    NOT NULL DEFAULT 0.10,
    emotional_tone   TEXT    NOT NULL DEFAULT 'neutral',  -- positive | neutral | negative | complex
    status           TEXT    NOT NULL DEFAULT 'active',   -- active | decaying | forgotten | disliked
    first_seen       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_mentioned   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mention_count    INTEGER NOT NULL DEFAULT 1,
    session_delta    REAL    NOT NULL DEFAULT 0.0,        -- accumulated delta this session, reset on close
    notes            TEXT,                                -- one-line factual note (e.g. reason for dislike)
    CHECK (interest_score BETWEEN -1.0 AND 1.0),
    CHECK (emotional_tone IN ('positive','neutral','negative','complex')),
    CHECK (status IN ('active','decaying','forgotten','disliked')),
    -- Hard rule: only Jose may exceed 0.69
    CHECK (is_jose = 1 OR interest_score <= 0.69)
);

CREATE INDEX IF NOT EXISTS idx_person_interest_score          ON person_interest(interest_score DESC);
CREATE INDEX IF NOT EXISTS idx_person_interest_last_mentioned ON person_interest(last_mentioned);
CREATE INDEX IF NOT EXISTS idx_person_interest_status         ON person_interest(status);

-- ============================================================
-- USER_PROFILES — structured static data about users
-- ============================================================
-- Stores semi-static user info (name, location, language) as JSON.
-- Dynamic facts (projects, preferences, goals) go to Mem0 with metadata.
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id    TEXT PRIMARY KEY,
    data       TEXT NOT NULL,                              -- JSON blob
    updated_at TEXT NOT NULL
);

-- ============================================================
-- RELATIONS — directed connections between THIRD PARTIES
-- ============================================================
-- IMPORTANT: relations are NEVER stored between Lumi and a person.
-- Lumi's stance toward a person is fully captured by:
--   person_interest.score  + person_interest.emotional_tone  + Mem0 memories.
-- This table models Jose's social graph from Lumi's perspective.
CREATE TABLE IF NOT EXISTS relations (
    relation_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    from_person_id   TEXT    NOT NULL,
    to_person_id     TEXT    NOT NULL,
    relation_type    TEXT    NOT NULL,    -- family | romantic | friendship | professional | conflict | unknown
    description      TEXT    NOT NULL,    -- Spanish, e.g. "Gloria es la madre de Jose"
    inferred         INTEGER NOT NULL DEFAULT 0,  -- 1 if Lumi inferred (only direct family per relation_policy.md)
    first_mentioned  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_mentioned   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mention_count    INTEGER NOT NULL DEFAULT 1,
    CHECK (relation_type IN ('family','romantic','friendship','professional','conflict','unknown')),
    CHECK (from_person_id != to_person_id),
    CHECK (from_person_id != 'lumi' AND to_person_id != 'lumi'),  -- enforce: no Lumi relations
    UNIQUE (from_person_id, to_person_id, relation_type),
    FOREIGN KEY (from_person_id) REFERENCES person_interest(person_id) ON DELETE CASCADE,
    FOREIGN KEY (to_person_id)   REFERENCES person_interest(person_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_relations_from ON relations(from_person_id);
CREATE INDEX IF NOT EXISTS idx_relations_to   ON relations(to_person_id);

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
