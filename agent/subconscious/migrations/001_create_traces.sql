-- LUMI traces.db
-- Conversation history and daily diary.
-- This is the SOURCE OF TRUTH for:
--   * Sequential conversation turns (history)
--   * Lumi's daily diary entries (diary)
--   * Mood state time-series (mood_logs)
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

-- ============================================================
-- DIARY — Lumi's narrative log
-- ============================================================
-- Topic-thread-level entries produced by the nightly consolidation cron.
-- One row per coherent topic identified by the LLM during the period window.
-- Replaces the previous session_summaries table.
--
-- entry_type allows future extensions:
--   'daily_thread'  — produced by generate_daily_diary (current)
--   'introspection' — reserved for weekly self-reflection (future)
--   'milestone'     — reserved for relational milestones (future)

CREATE TABLE IF NOT EXISTS diary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    period_start TEXT NOT NULL,           -- UTC ISO-8601, batch window start
    period_end   TEXT NOT NULL,           -- UTC ISO-8601, batch window end

    talked_at_ts        TEXT NOT NULL,    -- UTC ISO-8601, representative moment of the thread
    thread_span_minutes INTEGER,          -- duration of the thread, NULL if single-turn
    user_ids            TEXT NOT NULL,    -- JSON array of human participants
    topic_label         TEXT,             -- short snake_case tag
    summary             TEXT NOT NULL,    -- first-person paragraph in Colombian neutral Spanish

    lumi_state TEXT CHECK (lumi_state IS NULL OR json_valid(lumi_state)),
        -- JSON: mood snapshot from mood_logs closest to talked_at_ts

    entry_type TEXT NOT NULL DEFAULT 'daily_thread',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (entry_type IN ('daily_thread', 'introspection', 'milestone'))
);

CREATE INDEX IF NOT EXISTS idx_diary_period_end ON diary(period_end DESC);
CREATE INDEX IF NOT EXISTS idx_diary_talked_at  ON diary(talked_at_ts DESC);
CREATE INDEX IF NOT EXISTS idx_diary_topic      ON diary(topic_label);
CREATE INDEX IF NOT EXISTS idx_diary_type_end   ON diary(entry_type, period_end DESC);

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
    CHECK (trigger_source IN (
        'mood_check',
        'session_close',
        'morning_regression',
        'idle_decay',
        'event',
        'manual'
    )),
    CHECK (mood_valence >= -1.0 AND mood_valence <= 1.0),
    CHECK (mood_energy >= 0.0 AND mood_energy <= 1.0),
    CHECK (irritation >= 0.0 AND irritation <= 1.0),
    CHECK (focus_level >= 0.0 AND focus_level <= 1.0),
    CHECK (presence_need >= 0.0 AND presence_need <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_mood_logs_ts ON mood_logs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_mood_logs_session ON mood_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_mood_logs_trigger ON mood_logs(trigger_source, ts DESC);
