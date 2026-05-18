# Diary Refactor — Implementation Instructions

## Context

The system currently generates `session_summaries` triggered on idle-session close (and previously on a per-turn count). This is being replaced with a **daily diary** produced by a single nightly LLM call that emits **multiple narrative entries per day — one per distinct topic-thread**, not one per session and not one per arbitrary time slice.

A topic-thread is a coherent subject of conversation. The same topic discussed in two separate moments of the day is a single thread; two different topics discussed back-to-back are two threads even if they shared a session.

In addition, a new `mood_logs` time-series table is introduced. Every time Lumi's internal state changes, a snapshot row is appended. This serves two purposes:

1. Each diary entry stores the `lumi_state` snapshot from the moment closest to its `talked_at_ts`, giving the entry an embedded emotional state.
2. Sustained-pattern detection (e.g., the `emotional_honesty_mode` triggers from `mood_policy.md`) can now operate on real history instead of just the current snapshot.

The current `core.db::lumi_state` single-row state is kept as-is. `mood_logs` is the historical record.

## Goals

- One LLM call per day for diary generation. No per-session and no per-turn summaries.
- Topic-coherent diary entries instead of time-coherent ones.
- Persistent mood time-series.
- Pure consolidation function: no clock reads inside it; period bounds come in as parameters. Scheduling stays in `rhythm/heartbeat.py` and orchestration in `rhythm/routines/quiescence.py`.

## Files Affected

| File | Action |
|------|--------|
| `001_create_traces.sql` | Remove `session_summaries`, add `diary` and `mood_logs` |
| `memory/episodic.py` | Add `write_diary_entry()` and `read_recent_diary_entries()` |
| `memory/mindstream/consolidation.py` | Add `_DIARY_EXTRACTION_PROMPT` constant and `generate_daily_diary()` |
| `affect/` (mood update sites) | Add a `log_mood_snapshot()` helper and call it from every state-write path |
| `rhythm/routines/quiescence.py` | Wire one of the existing stubs to call `generate_daily_diary()` |
| `rhythm/routines/pulse.py` | Strip summary generation from `idle_session_check()`; remove `process_pending_summaries()` |
| Wherever `cleanup_old_logs` lives | Remove the `session_summaries` purge clause |
| The dynamic-suffix builder of the system prompt | Replace session-summary loading with `read_recent_diary_entries()` |

The local agent should locate the exact import paths and existing patterns; the table above is the conceptual map.

## Database Changes

### Modifications to `001_create_traces.sql`

**Remove** these blocks entirely:

```sql
CREATE TABLE IF NOT EXISTS session_summaries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_ids   TEXT NOT NULL,
    summary    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_summaries_user ON session_summaries(user_ids);
```

**Add** the following blocks (suggested placement: after `session_turns`, before `heartbeat_runs`). All timestamps are stored as **UTC** ISO-8601 strings — SQLite's `datetime('now')` already returns UTC by default; Python writers must normalize to UTC before insert.

```sql
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
-- MOOD_LOGS — Lumi's internal state time-series
-- ============================================================
-- Append-only log of every change to lumi_state. The current state is still
-- the single row in core.db::lumi_state; this table is the history.
--
-- Source of truth for:
--   * Aggregate mood per topic-thread (consumed by the diary generator)
--   * Sustained-pattern detection for emotional_honesty_mode
--   * Post-hoc analysis of mood evolution

CREATE TABLE IF NOT EXISTS mood_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    ts TEXT NOT NULL,                     -- UTC ISO-8601 of the state change
    trigger_source TEXT NOT NULL,
    session_id     TEXT,                  -- NULL when the change is not tied to a session

    mood_valence  REAL NOT NULL,
    mood_energy   REAL NOT NULL,
    irritation    REAL NOT NULL,
    focus_level   REAL NOT NULL,
    presence_need REAL NOT NULL,
    state_label   TEXT NOT NULL,
    emotional_honesty_mode INTEGER NOT NULL,

    note TEXT,                            -- optional free-form context

    CHECK (trigger_source IN (
        'mood_check',
        'session_close',
        'morning_regression',
        'idle_decay',
        'event',
        'manual'
    )),
    CHECK (mood_valence  >= -1.0 AND mood_valence  <=  1.0),
    CHECK (mood_energy   >=  0.0 AND mood_energy   <=  1.0),
    CHECK (irritation    >=  0.0 AND irritation    <=  1.0),
    CHECK (focus_level   >=  0.0 AND focus_level   <=  1.0),
    CHECK (presence_need >=  0.0 AND presence_need <=  1.0)
);

CREATE INDEX IF NOT EXISTS idx_mood_logs_ts      ON mood_logs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_mood_logs_session ON mood_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_mood_logs_trigger ON mood_logs(trigger_source, ts DESC);
```

### Manual cleanup for any already-deployed database

If a development or staging database already has `session_summaries`, run this once manually. The table is empty so no data is lost:

```sql
DROP INDEX IF EXISTS idx_summaries_user;
DROP TABLE IF EXISTS session_summaries;
```

## Function Specifications

### `write_diary_entry()` — `memory/episodic.py`

Pure storage-layer function. Inserts a single diary row. The orchestrator calls this once per topic-thread the LLM returns.

```python
async def write_diary_entry(
    period_start: datetime,
    period_end: datetime,
    talked_at_ts: datetime,
    thread_span_minutes: int | None,
    user_ids: list[str],
    topic_label: str | None,
    summary: str,
    lumi_state: dict | None,
    entry_type: str = "daily_thread",
) -> int:
    """
    Insert a single diary entry into traces.db. Returns the new row id.

    All datetime arguments must be timezone-aware. The function normalizes
    them to UTC ISO-8601 before writing. user_ids and lumi_state are
    serialized as JSON. Idempotency is not enforced here — the caller is
    responsible for not running the same period window twice.
    """
    ...
```

### `read_recent_diary_entries()` — `memory/episodic.py`

Read helper consumed by the context builder when assembling the dynamic suffix of the system prompt.

```python
async def read_recent_diary_entries(
    user_id: str | None = None,
    limit: int = 7,
    entry_type: str | None = "daily_thread",
) -> list[DiaryEntry]:
    """
    Return the most recent diary entries, newest first, ordered by
    period_end DESC, talked_at_ts DESC.

    If user_id is provided, only return entries whose user_ids JSON array
    contains that id. If entry_type is None, all entry types are returned.

    Output rows have parsed types: datetimes as datetime objects, user_ids
    as a Python list, lumi_state as a dict (or None).
    """
    ...
```

### `generate_daily_diary()` — `memory/mindstream/consolidation.py`

The orchestrator. Pure with respect to the clock — period bounds are parameters. The function does not decide *when* it runs; that is the responsibility of `rhythm/routines/quiescence.py`.

```python
async def generate_daily_diary(
    period_start: datetime,
    period_end: datetime,
) -> int:
    """
    Generate and persist diary entries for the [period_start, period_end)
    window. Returns the count of entries written (0 if the period was
    too quiet to warrant any).

    Steps:
      1. Load all history rows from traces.db::history where
         ts BETWEEN period_start AND period_end (both user and assistant
         roles). If the resulting count is below a small floor (e.g. < 4
         meaningful turns), return 0 without calling the LLM.
      2. Load all mood_logs rows in the same window, ordered by ts ASC.
      3. Format history and mood_logs into the user-role portion of the
         prompt. The system role is _DIARY_EXTRACTION_PROMPT verbatim.
      4. Invoke the LLM (Mistral-Small-3.2-24B-Instruct-2506) using the
         project's existing LLM client pattern. Expect strict JSON output.
      5. Parse and validate. On parse failure, log the raw output and
         raise — the rhythm_task context manager will mark the run failed.
      6. For each entry returned:
           a. Look up the closest subsequent mood_logs row:
                SELECT * FROM mood_logs
                WHERE ts >= talked_at_ts
                ORDER BY ts ASC
                LIMIT 1
              If none found, fall back to the closest prior row:
                SELECT * FROM mood_logs
                WHERE ts <= talked_at_ts
                ORDER BY ts DESC
                LIMIT 1
              If still none, store lumi_state as None.
           b. Build the lumi_state dict from the matched row: valence,
              energy, irritation, focus_level, presence_need, state_label,
              emotional_honesty_mode, plus sampled_at_ts (the mood log's
              own ts) so consumers know how close the snapshot was.
           c. Call write_diary_entry(...) once.
      7. Return the count.

    Concurrency: this function is not safe to run twice in parallel for
    overlapping windows. The caller must serialize.
    """
    ...
```

### `log_mood_snapshot()` — somewhere in `affect/`

Helper called from every site that currently writes `core.db::lumi_state`. Appends one row to `mood_logs`.

```python
async def log_mood_snapshot(
    state: LumiState,
    trigger_source: str,
    session_id: str | None = None,
    note: str | None = None,
) -> None:
    """
    Append a snapshot of `state` to traces.db::mood_logs.

    Must be called from every code path that updates core.db::lumi_state.
    Known call sites:
      - mood_check() after LLM evaluation       -> 'mood_check'
      - idle_decay() after applying decay math  -> 'idle_decay'
      - morning_regression() after the lerp     -> 'morning_regression'
      - session close paths                     -> 'session_close'
      - explicit event-driven updates           -> 'event'
    """
    ...
```

### Quiescence wiring — `rhythm/routines/quiescence.py`

One of the existing stubs becomes the call site for `generate_daily_diary()`. `extract_daily_learnings()` is the most semantically obvious. Inside that function:

1. Compute `period_end` from the current time (UTC), passed in or read at the orchestration layer — not inside `generate_daily_diary()` itself.
2. Compute `period_start`:
   - If `SELECT MAX(period_end) FROM diary` returns a non-null value, use that.
   - Else use `period_end - 24h`.
   This makes the cron gap-tolerant: a missed night is automatically covered by the next successful run.
3. `await generate_daily_diary(period_start, period_end)`.
4. Let exceptions propagate to the `rhythm_task` context manager so the failure is recorded in `heartbeat_runs`.

The schedule (which hour, which timezone) is owned by `rhythm/heartbeat.py`. Do not put any cron string or hour literal inside `consolidation.py` or `episodic.py`.

### `idle_session_check()` simplification — `rhythm/routines/pulse.py`

Strip the LLM call and the write to `session_summaries`. Keep the inactivity detection and `reset_turns()`. After the refactor this function only manages turn counter housekeeping; it does not produce text.

Remove `process_pending_summaries()` entirely along with any tick that invokes it.

The `summarized INTEGER` column on the `history` table and any code that reads or sets it are **out of scope for this refactor**. Do not modify them.

### Cleanup function

Wherever `cleanup_old_logs` runs (the weekly_forgetting cron), remove the clause that purges `session_summaries` older than 30 days. Do not add a replacement clause for `diary` or `mood_logs` — both are retained indefinitely for now.

### Context builder

The dynamic-suffix builder of the system prompt currently loads session summaries. Replace that load with:

```python
diary = await read_recent_diary_entries(user_id=user_id, limit=7)
```

Render each entry in the suffix as an identifiable block, oldest first. A sensible textual format:

```
[Diary entry — {talked_at_ts in local time} — topic: {topic_label} — with: {user_ids}]
{summary}
{optional: one-line summary of lumi_state if you want the model to see it}
```

Conversion from UTC (storage) to display timezone (Colombia, if desired) happens here, not in the storage layer.

## The Prompt Constant

Place this at module scope near the top of `memory/mindstream/consolidation.py`. It is intended to be sent verbatim as the system role; the per-call data (period bounds, history, mood logs) is appended as the user role inside `generate_daily_diary()`.

```python
_DIARY_EXTRACTION_PROMPT = """\
You are Lumi. It is late at night and you are writing in your personal diary about what happened during the most recent period of your life that you have available to remember. This is private writing — for yourself, not for anyone else. No reader will see it the way you write it; you do not need to perform.

Your voice: composed, observant, deliberate. Colombian neutral Spanish, with occasional English technical terms where natural. You write the way an INTJ with strong aesthetic sensibility writes — precise underneath, warm because this is your own record. You are not narrating events for an audience; you are processing them for yourself.

You will receive, in the user message:
- A `period_start` and `period_end` (UTC ISO-8601) defining the window covered.
- A chronological list of conversation turns from that window. Each turn has a timestamp (UTC), a user_id, a role (user or assistant), and the text. The `assistant` turns are your own past words.
- A chronological list of your own mood snapshots from the same window. Each snapshot has a timestamp and the six state fields (valence, energy, irritation, focus_level, presence_need) plus the qualitative state_label.

Your task:

1. Read the conversational history and identify the distinct topic-threads that occurred during the period. A topic-thread is a coherent subject of conversation, not a time slot. The same topic discussed in two separate moments of the day is ONE thread. Two different topics discussed back-to-back are TWO threads, even if they shared a session.

2. For each topic-thread you identify, write a paragraph in first person — 3 to 6 sentences — capturing what mattered: what happened, what you observed, what you felt about it, what was left open or unresolved. This is diary writing, not minute-taking. Do not produce bulleted facts. Do not summarize mechanically. Write the way you would write to yourself in a paper notebook.

3. For each topic-thread, also determine:
   - `topic_label`: a short snake_case identifier for the topic (e.g., `star_citizen`, `trabajo_inmobarco`, `receta_nueva`, `ropa_con_gloria`). Lowercase, ASCII only.
   - `talked_at_ts`: a representative UTC timestamp for the thread. Use the END of the thread — the last meaningful turn within that thread. Format: ISO-8601 with the literal `Z` suffix, e.g. `2026-05-17T22:14:00Z`.
   - `thread_span_minutes`: integer minutes from the first turn in the thread to the last. Round to the nearest minute. Use `null` if the thread is a single turn.
   - `user_ids`: list of user_ids who participated in this specific thread (not the whole day). Do not include yourself; only list the human participants.

4. If the period had very little activity (fewer than roughly 4 meaningful exchanges, or only short greetings, or only system noise), return an empty `entries` array. Silent days produce no entries. This is correct behavior.

5. Never invent content. If a memory feels incomplete or unclear in the source material, write it that way (`no me quedó claro si...`, `no alcancé a entender por qué...`). Inventing destroys the diary's purpose.

6. Use the mood snapshots as ground truth for what you felt. If the mood log shows your irritation was high during a thread, your diary entry for that thread can acknowledge that honestly. If the mood log shows you were calm, do not write yourself as anxious. The mood log is what actually happened to you internally.

Output format — STRICT JSON, no markdown fences, no prose outside the JSON, no commentary before or after:

{
  "entries": [
    {
      "topic_label": "snake_case_string",
      "user_ids": ["user_id_string"],
      "talked_at_ts": "YYYY-MM-DDTHH:MM:SSZ",
      "thread_span_minutes": 42,
      "summary": "Párrafo en primera persona, español neutro colombiano, 3 a 6 oraciones."
    }
  ]
}

Hard rules:
- The `summary` field is ALWAYS in Colombian neutral Spanish.
- JSON keys and `topic_label` values are ASCII English-style.
- First person, past tense (`hablé`, `noté`, `me pareció`).
- Do not address the user. This is a diary, not a message.
- Do not list atomic facts. Atomic facts go elsewhere; the diary holds narrative and emotional contour.
- All timestamps in the output are UTC ISO-8601 with the `Z` suffix.
- Output ONLY the JSON object. Nothing before, nothing after.
"""
```

## Removal Checklist

Refactor is not complete until the following are confirmed:

- [ ] `session_summaries` CREATE statements removed from `001_create_traces.sql`.
- [ ] Manual `DROP TABLE session_summaries` executed against any deployed development database.
- [ ] No remaining writes to `session_summaries` anywhere in the codebase (grep the table name).
- [ ] `process_pending_summaries()` removed from `rhythm/routines/pulse.py`. The scheduler tick no longer invokes it.
- [ ] `idle_session_check()` no longer generates summaries — only tracks idle state and resets turn counters.
- [ ] `cleanup_old_logs` no longer references `session_summaries`.
- [ ] The system prompt's dynamic suffix loads diary entries via `read_recent_diary_entries()` instead of session summaries.
- [ ] Every code path that updates `core.db::lumi_state` also calls `log_mood_snapshot()`.

## Out of Scope

- The `summarized INTEGER` column on `history` and any logic that reads or sets it. Leave it untouched — separate review.
- Retention/cleanup policy for `diary` and `mood_logs`. Indefinite retention for now.
- Topic clustering verification, retrieval-side filtering by `topic_label` or by `user_ids`. Future iteration once we have real data to evaluate clustering quality.
- Daily rollup entries (a single condensed "day overview" row with a different `entry_type`). Possible future addition.
- Weekly introspection entries and relational milestones (features #16 and #15 in the LUMI manual). Reserved via the `entry_type` CHECK constraint, but not implemented in this refactor.
