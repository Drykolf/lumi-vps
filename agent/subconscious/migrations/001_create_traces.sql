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
    ts TEXT NOT NULL
);

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
