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
    channel_id TEXT NOT NULL DEFAULT 'default',
    ts TEXT NOT NULL
);

-- ============================================================
-- DIARY — Lumi's narrative log
-- ============================================================
-- One row per day: a single first-person "page" written by the nightly
-- consolidation cron, covering everything that happened that day. Replaces the
-- previous topic-thread model (one row per topic).
--
-- entry_type allows future extensions:
--   'daily_page'    — produced by generate_daily_diary (current)
--   'introspection' — reserved for weekly self-reflection (future)
--   'milestone'     — reserved for relational milestones (future)
--
-- NOTE: the schema below replaces the old topic-thread table (period_start/end,
-- talked_at_ts, thread_span_minutes, topic_label, summary, lumi_state). Diary
-- rows are regenerated nightly, so the DROP discards disposable history.

--DROP TABLE IF EXISTS diary;
CREATE TABLE IF NOT EXISTS diary (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL UNIQUE,   -- 'YYYY-MM-DD', the day summarized
    people     TEXT NOT NULL,          -- JSON array of human user_ids
    threads    TEXT,                   -- JSON array of snake_case topic tags (index)
    page       TEXT NOT NULL,          -- first-person prose, Colombian neutral Spanish
    mood       TEXT CHECK (mood IS NULL OR json_valid(mood)),
        -- JSON: daily-average mood snapshot (5 dims + state_label + honesty flag)
    entry_type TEXT NOT NULL DEFAULT 'daily_page',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (entry_type IN ('daily_page', 'introspection', 'milestone'))
);

CREATE INDEX IF NOT EXISTS idx_diary_date      ON diary(date DESC);
CREATE INDEX IF NOT EXISTS idx_diary_type_date ON diary(entry_type, date DESC);

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
    channel_id TEXT NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_person_mentions_channel
    ON person_mentions(channel_id, created_at);

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
    channel_id TEXT,
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
CREATE INDEX IF NOT EXISTS idx_mood_logs_channel ON mood_logs(channel_id);
CREATE INDEX IF NOT EXISTS idx_mood_logs_trigger ON mood_logs(trigger_source, ts DESC);
