# Skill: Reflection Policy

## Purpose
Defines the **session close pipeline** — the orchestrated sequence that
runs when a session ends, ensuring the WRITE path is fully committed:
memory upgrades, score deltas, decay, mood update, and history cleanup.

This is the conductor. The other skills are the instruments. This skill
calls them in the right order.

---

## When does a session "close"?

A session is considered closed when ANY of these triggers fire:

| Trigger | Detection |
|---------|-----------|
| Explicit close from Jose | *"hasta luego"*, *"chao Lumi"*, *"ya, descansa"* — natural farewell phrases |
| Inactivity timeout | No turn for 5+ minutes after the last exchange |
| Channel disconnect | Discord voice leave, WhatsApp session timeout, OLV process stop |
| Heartbeat-detected end-of-day | At 23:00 COT if any session is still nominally open |

**Important:** the close pipeline is **idempotent**. If it runs twice on
the same session_id, the second run is a no-op (it sees the session
already marked closed and exits). This protects against duplicate
triggers from overlapping detectors.

---

## Pipeline stages (run in this order)

### Stage 1 — Snapshot the session

Read from `history.db`:
- All turns of the closing session
- Session start and end timestamps
- Channel of origin

Read from SQLite `persons`:
- All rows where `last_mentioned >= session_start` (i.e. touched this session)
- Their accumulated `session_delta` values

Read from Mem0 `history` (Mem0's own audit log):
- Operations applied during the session

This snapshot is the only input to the rest of the pipeline. Once captured,
the pipeline does not re-read live state during its own execution.

### Stage 2 — Extract memories

Call the Mem0 extractor (`mistral-small-3.2-24B`) on the session
transcript. Constraints from `memory_policy.md`:

- Spanish, third person, factual.
- One fact per memory item.
- Each memory MUST include `metadata.person_id` matching a `persons` row.
- Skip anything in the "What NEVER to store" list.

The extractor returns a list of `{person_id, fact_text}` candidates. Each
is added to Mem0 as a `fact` type via the standard `add_memory()` call,
which handles dedupe via Mem0's `history.db`.

For Lumi's own facts (rare — only if Jose said something definitional
about Lumi herself), use `add_lumi_memory()` with `agent_id="lumi"`.

### Stage 3 — Apply pending interest deltas

For each person row with `session_delta != 0.0`:

1. Apply the cap rules from `interest_policy.md`:
   - Positive cap: `session_delta` for non-Jose cannot push final score past `0.69`.
   - Per-session positive cap: `session_delta` for non-rehabilitation cannot exceed `+0.05`.
   - Negative deltas: no cap, but final score floored at `-1.0`.
2. Update `interest_score = MAX(MIN(interest_score, 0.69), -1.0)` (and `<= 1.0` for Jose).
3. Note threshold crossings — if score crossed `0.40` or `0.60` upward, mark for memory upgrade in Stage 5. If crossed below `0.10` from above, mark for downgrade.
4. Reset `session_delta = 0.0`.

Run as a single SQLite transaction.

### Stage 4 — Run inference pass for relations

Per `relation_policy.md`, scan for direct-family inference opportunities.
The inference is limited to parents-of-Jose → romantic between them, and
parents-of-Jose ↔ siblings-of-Jose → those parents are also parents of
the siblings.

Insert any new inferred rows with `inferred=1`. If a previously inferred
row's premise was deleted this session, delete the inferred row too.

### Stage 5 — Run memory upgrade/downgrade for crossed thresholds

For each person flagged in Stage 3:

**Upgrade (score crossed `0.40` or `0.60` upward):**
1. Re-read all turns of this session and recent past sessions where this
   person was mentioned.
2. Extract additional facts at the new tier per `memory_policy.md`.
3. Add to Mem0.

**Downgrade (score dropped below `0.10` after decay in Stage 6):**
1. Delete Mem0 facts with this `metadata.person_id`.
2. Keep the SQLite row but set `notes=NULL` (or only the dislike reason if score is negative).

### Stage 6 — Run decay

Per `interest_policy.md`:

The infrastructure layer runs a decay pass on all persons where is_jose=0 and interest_score >= 0 and last_mentioned is 28+ days ago."

For any rows that flipped to `status='forgotten'` this pass, schedule a
cleanup of their Mem0 facts (delete in Stage 5 logic, executed here).

### Stage 7 — Generate session_summary

If the session had 5+ turns, call the main LLM (`Qwen3.5-35B-A3B`) with a
short prompt:

```
Resume esta sesión con Jose en 2-3 oraciones, en español, tercera persona.
Enfócate en: temas tratados, decisiones tomadas, estado emocional general
de Jose. No incluyas hechos atómicos (ya extraídos aparte).
```

Save as Mem0 `session_summary` type with `user_id="jose"` and metadata
`{session_id, started_at, ended_at, channel}`.

### Stage 8 — Update user_profile

Every 5 sessions (counted by `session_summary` count for Jose), refresh
the `user_profile` JSON. Pull the last 5 session summaries plus the
existing profile, send to the main LLM:

```
Aquí está el perfil actual de Jose y los últimos 5 resúmenes de sesión.
Actualiza el perfil reflejando lo nuevo. Mantén la estructura JSON.
Conserva lo que sigue siendo cierto. Cambia lo que ha evolucionado.
Agrega nuevos campos sólo si claramente aplica.
```

Save as Mem0 `user_profile` (overwriting prior — only one active profile
exists at a time; the prior is archived in the `history.db` of Mem0).

### Stage 9 — Update lumi_state

Per `mood_policy.md`:

1. Compute deltas based on session events (interruption count, mistakes,
   warmth signals, mention of liked/disliked people, tool failures).
2. Apply caps (per-field cumulative cap of `0.30`).
3. Check `emotional_honesty_mode` triggers.
4. Write the updated state JSON to `lumi_state` table, key `internal_state`.

Note: this happens AFTER stage 7 because session_summary content can
inform the delta calculation.

### Stage 10 — Run skill_evolution detector (if enabled)

Per `skill_evolution.md`:

1. Run pattern detection across the recent session window.
2. If a pattern crosses threshold and no skill exists, generate a draft
   in `src/skills/_drafts/` and insert a row in `skill_proposals`.
3. Notify Jose via the next morning heartbeat that a proposal is pending
   review.

This stage is gated by a feature flag — disabled by default until Jose
opts in. See `skill_evolution.md` for the bootstrapping path.

### Stage 11 — Cleanup

1. Clear Mem0's `history.db` (the operations log) — it has done its job
   for this session and otherwise grows unbounded.
2. Mark the session as `closed` in the conversation `history.db`.
3. Log the close pipeline outcome (counts of facts added, scores changed,
   relations inferred, decay events, drafts proposed) to a rolling daily
   log file for debugging.

---

## Failure handling

Each stage runs in its own transaction or scope. If a stage fails:

| Stage | On failure |
|-------|-----------|
| 1, 2 | Abort pipeline; the session remains "open" — retry on next trigger |
| 3 | Roll back delta application; session_delta values stay non-zero for next attempt |
| 4 | Skip — inference is non-essential, can run next session |
| 5 | Skip the upgrade/downgrade; flag for retry on next close |
| 6 | Skip decay; will run next session (no harm in slight delay) |
| 7 | Skip summary generation; not all sessions need a summary |
| 8 | Skip profile update; will run on next 5th-session trigger |
| 9 | Skip mood update; lumi_state stays unchanged (acceptable degradation) |
| 10 | Skip skill_evolution; non-critical |
| 11 | Cleanup is best-effort; orphaned history.db rows are harmless |

**Hard rule:** stages 1–3 must all succeed for the pipeline to be
considered "complete enough" to mark the session closed. Otherwise, the
session is marked `'pending_reflection'` and retried at the next trigger.

---

## Pipeline summary

```
close_session(session_id)
├── 1. snapshot               (read-only, fast)
├── 2. extract memories       → Mem0 add_memory (per person)
├── 3. apply interest deltas  → SQLite UPDATE (transactional)
├── 4. infer relations        → SQLite INSERT (idempotent)
├── 5. memory tier upgrades   → Mem0 add/delete (conditional)
├── 6. decay                  → SQLite UPDATE
├── 7. session_summary        → Mem0 add (LLM call)
├── 8. user_profile (every 5) → Mem0 update (LLM call)
├── 9. lumi_state update      → SQLite UPDATE
├── 10. skill_evolution scan  → optional, draft + skill_proposals INSERT
└── 11. cleanup               → history.db clear, session marked closed
```

**Approximate cost per close:** 1 Mistral extraction call (~$0.0005),
1 main-LLM session_summary call (~$0.0002), occasional profile call
every 5 sessions (~$0.001). Total: under $0.001 per session in steady
state. Acceptable.
If the session mentions 3 or more people, batch the extraction into a single call with all relevant turns grouped by person, rather than one call per person.

---

## What this skill does NOT do

- Modify ongoing turn-by-turn behavior (that is the read path).
- Modify Lumi's identity or personality (those are static).
- Decide the *content* of memories (that is `memory_policy.md`).
- Decide the *deltas* themselves (those are `interest_policy.md` and
  `mood_policy.md`).

This skill only orchestrates **when** and **in what order** the others
run at session close.
