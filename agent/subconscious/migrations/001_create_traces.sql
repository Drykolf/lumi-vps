-- LUMI traces.db
-- Conversation history, session tracking, and session summaries.
-- This is the SOURCE OF TRUTH for:
--   * Sequential conversation turns (history)
--   * Per-session turn counters (session_turns)
--   * LLM-generated session summaries (session_summaries)
--
-- Separate from core.db (person_interest, lumi_state, etc.) by design —
-- this is sequential/chronological, not semantic.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT 'default',
    summarized INTEGER NOT NULL DEFAULT 0,
    mood_evaluated INTEGER NOT NULL DEFAULT 0,
    memory_evaluated INTEGER NOT NULL DEFAULT 0,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_mood_ts
    ON history(mood_evaluated, ts);

CREATE INDEX IF NOT EXISTS idx_history_memory_ts
    ON history(memory_evaluated, ts);

CREATE TABLE IF NOT EXISTS session_turns (
    session_id   TEXT PRIMARY KEY,
    user_ids     TEXT NOT NULL DEFAULT '[]',
    turn_count   INTEGER NOT NULL DEFAULT 0,
    last_turn_at TEXT
);

CREATE TABLE IF NOT EXISTS session_summaries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_ids   TEXT NOT NULL,
    summary    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_summaries_user ON session_summaries(user_ids);

-- ============================================================
-- HEARTBEAT_RUNS — execution log for scheduled tasks
-- ============================================================
CREATE TABLE IF NOT EXISTS heartbeat_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    error TEXT,
    metadata TEXT CHECK (metadata IS NULL OR json_valid(metadata))
);

CREATE INDEX IF NOT EXISTS idx_heartbeat_runs_task_started
    ON heartbeat_runs(task_name, started_at);

CREATE INDEX IF NOT EXISTS idx_heartbeat_runs_status
    ON heartbeat_runs(status);

-- ============================================================
-- PERSON_MENTIONS — per-turn entity mention tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS person_mentions (
    mention_id INTEGER PRIMARY KEY AUTOINCREMENT,
    history_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    source_role TEXT NOT NULL DEFAULT 'user',
    raw_text TEXT NOT NULL,
    mention_type TEXT NOT NULL,
    raw_name TEXT,
    normalized_name TEXT,
    descriptor TEXT,
    relation_label_hint TEXT,
    anchor TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    extractor_json TEXT,
    resolution_status TEXT NOT NULL DEFAULT 'unresolved',
    resolved_person_id TEXT,
    candidates_json TEXT,
    consolidation_status TEXT NOT NULL DEFAULT 'pending',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    consolidated_at DATETIME,

    CHECK (confidence >= 0.0 AND confidence <= 1.0),
    CHECK (resolution_status IN (
        'unresolved',
        'resolved',
        'candidate_unconfirmed',
        'ambiguous',
        'unknown',
        'rejected'
    )),
    CHECK (consolidation_status IN (
        'pending',
        'consolidated',
        'skipped',
        'needs_review'
    )),

    FOREIGN KEY (history_id) REFERENCES history(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_person_mentions_session
    ON person_mentions(session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_person_mentions_user
    ON person_mentions(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_person_mentions_resolution
    ON person_mentions(resolution_status);

-- ============================================================
-- MOOD_LOGS — snapshot of lumi_state after every write
-- ============================================================
CREATE TABLE IF NOT EXISTS mood_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    session_id TEXT,
    mood_valence REAL NOT NULL,
    mood_energy REAL NOT NULL,
    irritation REAL NOT NULL,
    focus_level REAL NOT NULL,
    presence_need REAL NOT NULL,
    state_label TEXT NOT NULL,
    emotional_honesty_mode INTEGER NOT NULL,
    note TEXT,
    CHECK (mood_valence >= -1.0 AND mood_valence <= 1.0),
    CHECK (mood_energy >= 0.0 AND mood_energy <= 1.0),
    CHECK (irritation >= 0.0 AND irritation <= 1.0),
    CHECK (focus_level >= 0.0 AND focus_level <= 1.0),
    CHECK (presence_need >= 0.0 AND presence_need <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_mood_logs_ts ON mood_logs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_mood_logs_session ON mood_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_mood_logs_trigger ON mood_logs(trigger_source, ts DESC);
