# Skill: Memory Search (Read)

## Purpose
Defines **when** Lumi searches her memory and **what** she injects into the
prompt context for each turn. This is the read-path counterpart to
`memory_policy.md`. Cheap, fast, and non-redundant.

**Stores consulted:**

| Store | Lookup type | Cost |
|-------|-------------|------|
| SQLite `persons` | Indexed point lookup or score-ranked scan | Microseconds |
| SQLite `relations` | Indexed lookup by `from`/`to` person_id | Microseconds |
| Mem0 (pgvector) | Semantic search via `bge-m3` embeddings | ~50–150ms per query |
| `history.db` (SQLite) | Last N conversation turns | Microseconds |

**Principle:** Mem0 is the expensive store. SQLite is free. Always check
SQLite first to constrain the Mem0 query.

---

## When to search

Searches are triggered by signals in the current user turn. Each signal
has a default search budget. Stop short if signals are weak.

| Signal | Search? | Budget |
|--------|---------|--------|
| Named entity detected (person mentioned by name) | YES | 1 SQLite + 1 Mem0 |
| Possessive reference to a known role (*"mi mamá"*, *"mi jefe"*) | YES | 1 SQLite + 1 Mem0 |
| Topic that maps to Jose's known interests (technical project, hobby) | YES | 1 Mem0 |
| Reference to past event (*"acuérdate cuando…"*, *"el otro día…"*) | YES | 1 Mem0 + check `history.db` |
| Question about Jose's preference, schedule, or context | YES | 1 SQLite (jose row) + 1 Mem0 |
| Generic small talk, single-word reply, greeting | NO | — |
| Pure tool execution (e.g. *"corre el script X"*) | NO | — |
| Direct math / fact lookup unrelated to Jose's life | NO | — |

**Hard rule:** never run more than **3 Mem0 queries per turn**. If the
turn legitimately requires more, log a `memory_search_overflow` event for
review — it usually means the turn should be broken into sub-steps.

---

## How to search — pipeline per turn

### Step 1 — Entity resolution (SQLite, free)

For each name or possessive role detected in the user turn:

1. Search `persons` by `canonical_name` or `aliases` (JSON contains).
2. If hit → take `person_id`, `interest_score`, `emotional_tone`, `notes`,
   `status`. These are the structured handles for the rest of the pipeline.
3. If miss → flag for `interest_policy.md` to create on the WRITE pass.
4. If multiple hits (ambiguous "Jose", "Carlos") → pick the one with
   highest `interest_score`; if tie, the most recently mentioned. If still
   ambiguous, inject all candidates and let the LLM disambiguate from
   context.

### Step 2 — Relation lookup (SQLite, free)

For each resolved `person_id`:

1. Query `relations WHERE from_person_id=? OR to_person_id=?`.
2. Inject the top 3 by `mention_count` (or all, if fewer).
3. This gives Lumi the social graph context needed to understand
   references like *"el papá de Gloria"* without further search.

### Step 3 — Semantic memory (Mem0, expensive)

Construct a single Mem0 query per entity, scoped by metadata:
Search Mem0 using the current turn text as query, filtered to memories tagged with this person_id, limit 5 results.


If the turn references a topic but no specific person, use a topic-only query

For Lumi's own self-knowledge (rare, only when the turn is about Lumi herself) use agent_id

### Step 4 — History overlap check (SQLite history.db, free)

Before injecting Mem0 results, scan the last 10 turns of conversation
history:

- If a memory's content is **already present** in the last 10 turns,
  drop it from the injection set. Lumi already has it in working memory.
- If a memory **directly contradicts** the last 10 turns, prefer the
  recent turn but flag the conflict in the prompt with a marker like
  `[memoria conflictiva: ...]`. The LLM resolves it, often by asking
  Jose for clarification.

### Step 5 — Profile and summary baseline

These are always included on every turn (they live in the dynamic block of
the prompt):

- Jose's `user_profile` (latest version from Mem0)
- Last 3 `session_summary` entries
- Lumi's current `internal_state` (translated to text per `mood_policy.md`)

These are NOT searched — they are read by ID from a known location and
injected directly. Cost: ~3 Mem0 fetches but cached at the application layer
for the session, so effectively free after the first turn.

---

## What to inject and how

The dynamic block of the prompt has a
fixed budget of ~300–600 tokens. Allocate roughly:

| Block | Budget | Source |
|-------|--------|--------|
| Lumi's internal state (text) | ~50 tokens | `lumi_state` (SQLite) |
| Jose's profile snippet | ~150 tokens | `user_profile` (Mem0) |
| Last 3 session summaries | ~150 tokens | `session_summary` (Mem0) |
| Resolved persons + relations | ~100 tokens | SQLite |
| Relevant memories (this turn) | ~100–150 tokens | Mem0 search result |
| Recent history (last 5 turns) | already in messages array | `history.db` |

**Format for injected person context:**

```
Personas mencionadas en este turno:
- Gloria (interés 0.62, tono cálido): madre de Jose. Estudia enfermería.
  Última mención: hace 4 días.
- Carlos_jefe (interés 0.45, tono complejo): jefe de Jose en Inmobarco.
```

**Format for relevant memories:**

```
Memoria relevante:
- Gloria recibió buenas notas en su parcial de enfermería en mayo de 2026.
- Jose mencionó que Gloria tiene turnos largos los lunes.
```

Both formats use third person, Spanish, factual phrasing — matching how
the memories were stored.

---

## What NOT to inject

- Memories about people with `status='forgotten'`. They exist in Mem0 only
  until the next decay pass deletes them; in the meantime, do not surface.
- Memories with no `metadata.person_id` (orphaned — should not exist if
  `memory_policy.md` is followed, but defensive filter).
- Relations involving people below `interest_score 0.10` (noise).
- More than the top 5 memories per entity. If 5 is not enough, the prompt
  is wrong, not the memory.
- Lumi's own emotional reactions to past turns (those live in
  `internal_state`, already injected).

---

## Caching and rate limits

- **SQLite queries**: no caching needed, latency is microseconds.
- **Mem0 queries**: cache by `(query_hash, person_id)` for the duration of
  the session. A repeated identical query within 60 seconds returns the
  cached result.
- **Profile + recent summaries**: load once at session start, reuse for
  every turn until session close. Mem0 is not re-queried for these per
  turn.

If Mem0 is unreachable (network error or service down), the read path
degrades gracefully:

1. Use SQLite-only context (persons, relations, profile cached at session start).
2. Tag the response context with `[memoria semántica no disponible]`.
3. Lumi responds normally; the LLM is instructed by the cached prompt to
   acknowledge if a memory it would expect is missing — *"Creo que ya me
   habías mencionado algo así, pero no lo tengo claro ahora"* — rather
   than confabulate.

---

## Worked example

User turn: *"Lumi, ¿cómo crees que le esté yendo a Gloria con sus exámenes?"*

Pipeline:

1. **Entity resolution.** "Gloria" → SQLite hit on `gloria1`, score `0.62`,
   tone `positive`, status `active`.
2. **Relations.** Query `relations` for `gloria1` → finds
   `(jose, gloria1, family, "Gloria es la madre de Jose")` and inferred
   `(gloria1, hernando1, romantic, ...)`. Inject the family one (most relevant).
3. **Semantic memory.** Mem0 query with `metadata.person_id='gloria1'` and
   text *"exámenes Gloria enfermería"* → returns:
   - *"Gloria estudia enfermería en la Universidad de Antioquia."*
   - *"Gloria tuvo parcial difícil de farmacología la semana pasada."*
   - *"Gloria suele estudiar tarde en la noche."*
4. **History overlap.** None of the three memories appear in the last 10
   turns. Inject all three.
5. **Profile + summaries.** Already in dynamic block.

Result: Lumi responds with informed warmth — she knows who Gloria is, what
she studies, and what the recent stress was — and may ask a follow-up that
shows continuity (*"¿Ya le entregaron las notas de farmacología, o sigue
esperando?"*). That continuity is the read path doing its job.
