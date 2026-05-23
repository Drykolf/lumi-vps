# LUMI VPS — Phase 4 Unified Plan

**Last updated:** May 23, 2026 (Block 2 redesigned to nightly + Block 5 partial wire; providers updated to 8)
**Source:** Merged from 3 sources:
- `.architecture/plan.md` (original Phase 4 plan)
- `.architecture/phase4_known_persons_read_path_plan.md` (Phase 4A — schema migration + social read-path)
- Full codebase audit of `agent/` (45 Python files)

**Active phase:** 4 (Mem0 + semantic memory — social features)
**Next target:** Block 5 remaining subs (update_profiles, update_relations, consolidate_daily_memories, cleanup_memory_tiers, analyze_daily_tasks) + weekly decay wiring

**Status:**
- **Block 1** (read-path) shipped May 21, 2026 — per-turn third-party entity resolution + injection is live.
- **Block 2** (interest deltas) shipped May 21, 2026 — **redesigned to nightly batch** (Option 1, see decision below). `consolidate_person_interest` lives in quiescence as step 2.
- **Block 4** (emotional honesty mode injection) **verified shipped** — implemented in `working_memory.py:210-218`.
- **Block 5** (nightly stubs) — 2 of 6 subs wired (`consolidate_entity_mentions`, `consolidate_person_interest`); 4 still stubbed (`update_profiles`, `update_relations`, `consolidate_daily_memories`, `cleanup_memory_tiers`, `analyze_daily_tasks`); weekly decay still stub.
- **Block 3** (mood eval involved_people) — deferred to next phase.
- **Block 6** (attitude policy dynamic injection) — deferred to next phase.

**Decision locked: nightly consolidation over per-turn evaluation.**
Per-turn delta evaluation was deprecated. The schema already supported batch
consolidation (`person_mentions.consolidation_status='pending'`), a nightly LLM
call calibrates magnitude better than discrete heuristics, and the rhythm
aligns with Lumi's reflective character. See `interest_policy.md` (updated)
for the canonical timing tables.

**Note:** Phase 4A (schema migration from `person_interest`/`user_profiles` → `known_persons`/`relations`) is **fully implemented**. All social.py functions, resolution engine, and legacy wrappers exist and work. The gap is wiring them into the prompt builder.

---

## Architecture (current, verified)

```
agent/
├── presence/app.py              → FastAPI v0.4.0 entrypoint (root_path="/lumi")
├── perception/websocket.py       → MCP WebSocket bridge VPS↔PC
├── cognition/
│   ├── stream.py                 → cycle() orchestrator + _entities_check()
│   ├── stimulus.py               → explicit save handler + long task dispatch
│   ├── working_memory.py         → prompt builder (cached prefix + dynamic suffix)
│   ├── attention.py              → keyword classifier (4 types)
│   └── intention.py              → tool detection + registration
├── expression/
│   ├── synapses.py               → LLM factory (2 model groups, exponential backoff)
│   └── providers/                → 8 model providers (Gemma4, Qwen3.5-35B, Step, Qwen3-235B, Nemotron, Mistral, DeepSeek, Qwen9B)
├── memory/
│   ├── __init__.py               → Public API (single import point)
│   ├── semantic.py               → Mem0 REST client (add, search, search_person, save_explicit)
│   ├── episodic.py               → traces.db: history, mood_logs, diary
│   └── mindstream/
│       ├── social.py             → known_persons CRUD, relations, aliases, resolve, add_delta, run_decay, infer_family
│       ├── mentions.py           → person_mentions table (traces.db)
│       ├── consolidation.py      → LLM-powered diary entry generation
│       └── cleanup.py            → periodic DB pruning (history, mood_logs, heartbeat_runs)
├── affect/
│   ├── mood.py                   → Mood CRUD (state, deltas, morning_reset, sleep_stage, honesty_mode)
│   └── evaluation.py             → idle_decay() + LLM contextual mood evaluation
├── faculties/                    → BaseTool + BraveSearch + registry + dispatcher
├── rhythm/
│   ├── heartbeat.py              → APScheduler job registration
│   ├── cadence.py                → Timing constants
│   ├── state.py                  → Execution tracker (heartbeat_state / heartbeat_runs)
│   └── routines/
│       ├── pulse.py               → 15min tick: mood check, idle decay
│       ├── morning.py             → 7am daily: morning_regression() → wired
│       ├── quiescence.py          → 3am nightly: 4 of 6 subs stubs, 1 partial (update_user_profiles=pass), 1 wired (extract_daily_learnings)
│       └── forgetting.py          → Mon 4am: cleanup wired, interest_decay=stub(...)
├── identity/
│   ├── lumi_soul.md              → Core personality
│   ├── attitude.md               → Expressive framework
│   └── principles/               → 7 policy docs (memory_search, interest, mood, etc.)
├── subconscious/                  → DB singleton layer (traces.db + core.db)
└── substrate/                     → Shared logger
```

### Key schema changes since original plan

| Old (plan.md) | New (actual code) |
|---|---|
| `person_interest` table | `known_persons` table (core.db) |
| `user_profiles` table | Merged into `known_persons` + Mem0 |
| `session_summaries` table | `diary` table (traces.db) |
| No mention tracking | `person_mentions` table (traces.db) |
| `_memory_check()` in working_memory.py | `_entities_check()` in stream.py |

---

## What Works (verified from code)

| System | Status | File |
|--------|--------|------|
| **chat endpoint** classify→dispatch→context→tools→LLM→stream | ✅ | `stream.py:121` |
| **explicit save** "guarda esto" → LLM preprocessing → Mem0 | ✅ | `stimulus.py`, `stream.py:138` |
| **web search tool** Brave Search via keyword router + tool check | ✅ | `intention.py`, `stream.py:148` |
| **tool check optimization** Lightweight 500-token check | ✅ | `intention.py` |
| **diary consolidation** LLM-generated nightly diary entries | ✅ | `consolidation.py:169` |
| **scheduler heartbeat** 15min + 7am + 3am + Mon 4am | ✅ | `heartbeat.py` |
| **auto-registration** New user_id → known_persons row on first chat | ✅ | `social.py:143` |
| **user profiles** JSON in known_persons (aliases_json, notes) + Mem0 | ✅ | `social.py` |
| **personality** lumi_soul.md + attitude.md → cached system prefix | ✅ | `working_memory.py:36` |
| **internal state** Numeric mood model (5 fields + label + sentence) | ✅ | `mood.py` |
| **idle decay** Deterministic per-hour decay toward floors/caps | ✅ | `evaluation.py:106` |
| **morning reset** 7am regression (lerp) toward baseline | ✅ | `mood.py:187`, `morning.py:8` |
| **mood evaluation** Hourly LLM eval via lightweight model | ✅ | `pulse.py:26`, `evaluation.py:238` |
| **sleep stages** awake/drowsy/sleepy/sleeping injected into prompt | ✅ | `mood.py:74`, `working_memory.py:65` |
| **entity detection** _entities_check() LLM call per turn | ✅ | `stream.py:54`, called at `:144` |
| **mention persistence** Raw entities saved to person_mentions table | ✅ | `stream.py:112`, `mentions.py:12` |
| **entity resolution** Deterministic resolver wired per turn | ✅ | `stream.py:_resolve_entities`, `social.py:627` |
| **resolution persistence** Stamp `resolution_status`/`resolved_person_id`/`candidates_json`/`resolved_at` | ✅ | `mentions.py:update_mention_resolution`, called in `_finalize_turn` |
| **resolved persons in prompt** Token-budgeted block injected into dynamic suffix | ✅ | `working_memory.py:_format_entity_sections` |
| **speaker profile in prompt** `[Usuario]` block driven by `get_known_person()` | ✅ | `working_memory.py:_format_speaker_block` |
| **scoped Mem0 search** `search_person_relevant()` called per resolved person | ✅ | `stream.py:_resolve_entities` |
| **person mention increments** `increment_person_mention()` per resolved entity | ✅ | `stream.py:_finalize_turn` |
| **descriptor-only resolution** "mi mamá" resolves via relations without raw_name | ✅ | `social.py:find_person_candidates_by_name` |
| **assistant-leak guard** Drop `anchor=Lumi AND pid=user_id` (echo of user's name) | ✅ | `stream.py:_resolve_entities` |

---

## Code Exists But Is NOT Wired / NOT Tested

| System | Status | Location |
|--------|--------|----------|
| **Mem0 fact extraction (add_memory)** | ❌ Never called from agent loop | `semantic.py:26` exists but stream.py never imports it |
| **Entity resolution** | ✅ DONE 2026-05-21 — wired via `_resolve_entities` | `stream.py:_resolve_entities`, calls `social.py:627` |
| **Scoped Mem0 search (per person)** | ✅ DONE 2026-05-21 — called when status=resolved | `stream.py:_resolve_entities`, `semantic.py:75` |
| **Resolved persons in prompt** | ✅ DONE 2026-05-21 — entities_context plumbed end-to-end | `working_memory.py:build_messages` |
| **User info/interest in prompt** | ✅ DONE 2026-05-21 — replaced legacy stub with `_format_speaker_block` | `working_memory.py` |
| **interest deltas** | ✅ DONE 2026-05-21 — nightly LLM via `consolidate_person_interest` | `consolidation.py:consolidate_person_interest`, calls `social.py:add_delta` |
| **entity mention consolidation** | ✅ DONE 2026-05-21 — nightly LLM resolves pending mentions, creates new persons, deletes anonymous | `consolidation.py:consolidate_entity_mentions` |
| **person mention increments** | ✅ DONE 2026-05-21 — moved from per-turn to nightly via `bump_mention` | `social.py:bump_mention`, called from `consolidate_entity_mentions` |
| **interest decay** | ❌ `run_decay()` exists, weekly cron stub is `...` | `social.py:874`, `forgetting.py:19` |
| **relations (read)** | ✅ DONE 2026-05-21 — `get_relations()` called per resolved person | `social.py:303` |
| **relations (write)** | ❌ `add_relation()` not called in conversation flow; nightly `update_relations` is stub | `social.py:243`, `quiescence.py:update_relations` |
| **family inference** | ❌ `infer_family_relations()` never triggered; would live in `update_relations` | `social.py:910`, `quiescence.py` |
| **involved people in mood eval** | ❌ `mood_check()` passes `None`, `_build_eval_context()` still says `"# TODO"` (Block 3 deferred) | `pulse.py:74`, `evaluation.py:211` |
| **emotional honesty mode** | ✅ DONE — implemented in working_memory dynamic suffix | `working_memory.py:210-218` |
| **nightly quiescence** | 🟡 2 of 6 subs wired (entity_mentions, person_interest); 4 still stubs | `quiescence.py` |
| **weekly interest decay** | ❌ `weekly_interest_decay()` is `...` | `forgetting.py:19` |
| **attitude policy injection** | ❌ Not started (Block 6 deferred) | |

---

## Phase 4 — Remaining Work (6 blocks, re-verified)

### Block 1 — Third-Party Entity Recognition Pipeline ✅ SHIPPED 2026-05-21

End-to-end per-turn resolution + injection is live. Mentions persist with
resolution outcome; nightly write-path (Step 3 — seeding new persons) is
deferred to Block 5 per locked plan decision.

**Files touched:**
- `agent/cognition/stream.py` — new `_resolve_entities()`, `_slim_candidates()`; extended `_finalize_turn()` to stamp resolution + bump counters
- `agent/cognition/working_memory.py` — `build_messages` accepts `entities_context`; new helpers `_format_speaker_block`, `_format_entity_sections`, `_dedup_memories`
- `agent/memory/mindstream/mentions.py` — new `update_mention_resolution()`
- `agent/memory/mindstream/social.py` — minimal fix to `find_person_candidates_by_name` so descriptor+anchor resolution works without raw_name
- `agent/memory/__init__.py` — exports `update_mention_resolution`

**Final wiring:**

| Step | Action | Source | Status |
|------|--------|--------|--------|
| 1 | Call `_entities_check(message, sid, user_id)` per turn | `stream.py:_entities_check` | ✅ |
| 2 | Entity resolution: `resolve_person_mention()` per entity | `stream.py:_resolve_entities`, `social.py:627` | ✅ |
| 3 | Miss → seed `ensure_known_person()` | nightly only (Block 5) | 🔵 deferred |
| 4 | Hit → load `known_person` row + `get_relations(person_id)` | `stream.py:_resolve_entities` | ✅ |
| 5 | Scoped Mem0 search: `search_person_relevant()` | `stream.py:_resolve_entities` | ✅ |
| 6 | Dedup against last 10 turns in history | `working_memory.py:_dedup_memories` | ✅ |
| 7 | Token-budgeted injection: `"Personas mencionadas: ..."` block | `working_memory.py:_format_entity_sections` | ✅ |
| 8 | Persist resolution outcome to `person_mentions` | `mentions.py:update_mention_resolution` | ✅ |
| 9 | `increment_person_mention(person_id)` per resolved entity | `stream.py:_finalize_turn` | ✅ |
| -- | Uncomment + adapt user info/interest block | `working_memory.py:_format_speaker_block` | ✅ |

**Guards added (not in original spec, surfaced during impl):**
- **Self-mention drop:** entity resolves to speaker (`pid == user_id`) → flagged `is_self_mention=True`, skipped in injection (speaker block already covers it), still persisted.
- **Assistant-leak guard:** entity anchored to Lumi/asistente AND pid == user_id → drop. Prevents the extractor from echoing Lumi's prior turn ("Buenas tardes, Jose") back as a third-party mention. Lumi-anchored mentions of *third parties* (e.g. "es el Jose Luis del trabajo?") still flow normally.

**Out-of-scope variant (already mentioned, no profile yet):** `unknown` resolutions inject a single-line `[Sin perfil]` note (capped 3 per turn) so Lumi acknowledges new names gracefully without inventing context.

**Format target (matches what ships):**
```
Personas mencionadas en este turno:
- Gloria (interés 0.62, tono cálido): madre de Jose. Estudia enfermería.
  Última mención: hace 4 días. Relación: family.
- Carlos_jefe (interés 0.45, tono complejo): jefe en Inmobarco.
  Relación: profesional.

Memoria relevante:
- Gloria recibió buenas notas en su parcial de farmacología en mayo 2026.
```

**Resolution scoring rules** (implemented in `social.py:410-500`):

| Match type | Score |
|---|---|
| Canonical full name exact | 1.00 |
| Confirmed full_name alias exact | 0.99 |
| Confirmed alias (nickname/role) exact | 0.98 |
| Descriptor + matching relation | 0.96 |
| Canonical first name only | 0.60 |
| Unconfirmed alias exact | 0.55 |
| Canonical substring match | 0.45 |
| Relation-connected weak name boost | +0.15, max 0.85 |

**Resolution state semantics** (critical for Block 1 wiring):

| State | Behavior |
|---|---|
| `resolved` (score ≥ 0.96) | Use profile/relations, **search Mem0 scoped to person_id**, inject fully |
| `candidate_unconfirmed` (single candidate < 0.96) | Inject hint; Lumi should ask natural confirmation; **NO scoped Mem0** |
| `ambiguous` (multiple candidates) | Lumi must ask "¿cuál persona?"; NO scoped Mem0 |
| `unknown` (no candidates) | Don't create in read-path; quiescence/write-path decides later |

**Hard constraints:**
- Never resolve by global name alone — must anchor to speaker user_id via relations or alias
- Only search Mem0 scoped (`search_person_relevant`) if `resolution.status == 'resolved'`
- `interest_score` and `last_mentioned` are ordering hints only, never resolution signals

**Depends on:** nothing — all building blocks exist

---

### Block 2 — Interest Deltas (nightly batch) ✅ SHIPPED 2026-05-21

**Redesigned from per-turn to nightly batch (Option 1).** Per-turn evaluation
was retired; deltas are now computed once per night by an LLM consolidator
that reviews the full day's mentions, transcripts, and emotional context per
person, then applies a calibrated delta via `add_delta()`.

**Implementation:** `consolidate_person_interest(affected_person_ids)` in
[agent/memory/mindstream/consolidation.py](../agent/memory/mindstream/consolidation.py).
Receives the set of person_ids touched by `consolidate_entity_mentions` (step
1), groups their consolidated mentions, builds an LLM payload (current score,
emotional_tone, today's mention summaries, turn excerpts, relations, mood
snapshots), and asks the LLM to propose `{person_id, delta, new_emotional_tone?, reason}`.

**Jose is excluded** — his floor 0.70 is preserved by `add_delta`'s built-in
cap, and the consolidator skips him to avoid LLM noise.

**Per-turn change:** `increment_person_mention()` removed from `_finalize_turn`
([stream.py](../agent/cognition/stream.py)) — `mention_count` and
`last_mentioned` are now updated only by the nightly `bump_mention()` call,
giving a single source of truth for known_persons writes.

**Files touched (shipped):**
- `agent/memory/mindstream/consolidation.py` — new `consolidate_person_interest`
- `agent/memory/mindstream/mentions.py` — new `get_pending`, `mark_consolidated`, `update_consolidation_status`, `delete_mention`, `get_consolidated_grouped_by_person`
- `agent/memory/mindstream/social.py` — new `bump_mention`, `set_emotional_tone`, `list_known_persons_minimal`, `list_relations_all`
- `agent/memory/episodic.py` — new `get_history_grouped_by_session`, `get_turns_by_ids`, `get_mood_logs_since`
- `agent/memory/__init__.py` — public API exports
- `agent/cognition/stream.py` — removed per-turn increment
- `agent/identity/principles/interest_policy.md` — updated to nightly-batch design

---

### Block 3 — Enrich Mood Evaluation with Involved People 🔵 DEFERRED

`evaluate_mood()` in `evaluation.py` accepts `involved_people: dict | None` but `pulse.py:mood_check()` always passes `None`. The prompt says `"#Involved people:\n# TODO"`.

**Status:** Not in current scope. Block 2 (nightly interest) is independent —
mood eval can read the **already-updated** `interest_score` from the previous
night when this block ships.

**What to build (when picked up):**
- In `mood_check()` → build an `involved_people` dict from the session's unevaluated turns:
  - For each third party mentioned, bundle: `known_person` row + `relations`
- Pass it into `evaluate_mood(messages, current, involved_people=involved)`
- Fix `_build_eval_context()` line 211: replace `"# TODO"` with actual structured JSON

**Files touched:** `agent/rhythm/routines/pulse.py`, `agent/affect/evaluation.py`

**Depends on:** Block 1 (✅ shipped). Independent of Block 2.

---

### Block 4 — Wire Emotional Honesty Mode into Context ✅ SHIPPED

Already implemented in [agent/cognition/working_memory.py:210-218](../agent/cognition/working_memory.py#L210-L218).
Reads `state["emotional_honesty_mode"]` from `get_state()` and injects a
contextual block when active. The negative_load hysteresis (commit `ecd1db9`)
manages the flip; this block consumes it.

---

### Block 5 — Wire Stubs to Real Code 🟡 PARTIAL

#### 5a — Weekly interest decay (`forgetting.py:19`) ❌ stub
```python
# Current: ...
# Fix:
from agent.memory import run_decay
run_decay()  # Already implemented in social.py:874
```
Also wire `decay_inactive_people()` and `forget_stale_people()` if needed.

#### 5b — Nightly quiescence — new orchestration order

The nightly `nightly_quiescence()` runs these subs in order (see
[quiescence.py](../agent/rhythm/routines/quiescence.py)):

| # | Sub-function | What it does | Status |
|---|--------------|-------------|--------|
| 1 | `consolidate_entity_mentions()` | LLM resolves all pending mentions, creates new persons (with slug person_id), deletes anonymous mentions, bumps mention_count/last_mentioned | ✅ WIRED 2026-05-21 |
| 2 | `consolidate_person_interest(affected_ids)` | LLM evaluates per-person deltas based on day's mentions + transcripts, applies via `add_delta` | ✅ WIRED 2026-05-21 |
| 3 | `update_profiles(affected_ids)` | Extract new facts (notes, aliases, tone refinements) from today's turns and update known_persons | ❌ stub |
| 4 | `update_relations(affected_ids)` | Detect new relation patterns + apply `infer_family_relations()` | ❌ stub |
| 5 | `consolidate_daily_memories()` | Extract atomic facts per person from today's turns → Mem0 via `add_memory()` | ❌ stub |
| 6 | `extract_daily_learnings()` | Generate diary entries via `generate_daily_diary()` | ✅ WIRED |
| 7 | `cleanup_memory_tiers()` | Apply `run_decay()`, downgrade Mem0 for threshold-crossing persons, delete `status='forgotten'` after grace period | ❌ stub |
| 8 | `analyze_daily_tasks()` | Detect pending tasks mentioned → store in `skill_proposals` | ❌ stub |

**Justification of order:**
- Mentions first — everything else needs resolved `person_id`s.
- Interest second — profile/relations/Mem0 use the updated score to decide priorities.
- Profile/Relations third-fourth — operate on the stabilized roster.
- Mem0 fifth — long-term store, after the roster + scores are final.
- Diary sixth — narrative retrospective, reads everything above.
- Cleanup seventh — destructive, runs last.
- Tasks eighth — independent.

**Files touched:** `agent/rhythm/routines/forgetting.py`, `agent/rhythm/routines/quiescence.py`

**Removed/migrated:**
- `update_relationship_memory()` — split into `update_profiles` + `update_relations`. Kept as no-op shim for backwards compat.
- `update_user_profiles()` — no-op (table removed).

---

### Block 6 — Attitude Policy Dynamic Injection 🔵 DEFERRED

`attitude.md` is loaded into the cached prefix alongside `lumi_soul.md`, but the dynamic rules (score-driven posture, curiosity gate, reality filter) are not injected per-turn based on current context.

**What to build (when picked up):**
- In `_build_dynamic_suffix()`, inject 1-2 line summaries based on context:
  - If any mentioned person has `interest_score < 0.10` → `"[Postura] Persona con bajo interés. Respuestas neutras, sin calidez extra."`
  - If any mentioned person has `interest_score < 0` → `"[Postura] Persona en zona negativa. Respuestas mínimas, formales, sin apertura personal."`
  - If `emotional_honesty_mode` is active → `"[Postura] Modo honesto: franqueza sobre diplomacia."`

**Files touched:** `agent/cognition/working_memory.py`

**Depends on:** Block 1 (✅ shipped — needs interest scores), Block 4 (✅ shipped — flag available)

---

### Additional Item: Mem0 Fact Extraction Per Turn

`add_memory()` in `semantic.py:26` exists and is exported from `agent/memory/__init__.py` but is **never called from the agent loop**. The plan incorrectly claimed this was working.

**What to build:**
- In `_finalize_turn()` or after it in `cycle()`, call `add_memory()` with the last exchange to extract facts into Mem0
- This should happen for normal chat turns (not long_task/explicit_save)

**Files touched:** `agent/cognition/stream.py`

**Depends on:** nothing

---

## Implementation Order (updated)

```
Session 1: Block 1 — Read-path entity pipeline ✅ SHIPPED 2026-05-21
Session 2: Block 4 — Emotional honesty injection ✅ SHIPPED (prior work)
Session 3: Block 2 (redesigned) + Block 5 partial ✅ SHIPPED 2026-05-21
           → consolidate_entity_mentions (nightly step 1) in consolidation.py
           → consolidate_person_interest (nightly step 2) in consolidation.py
           → Reorganized nightly_quiescence with new 8-step order
           → Removed per-turn increment_person_mention (moved to nightly)
           → Updated interest_policy.md to nightly-batch design

Session 4 (next): Block 5 remaining
           → update_profiles (step 3)
           → update_relations (step 4) + infer_family_relations
           → consolidate_daily_memories (step 5) → add_memory() to Mem0
           → cleanup_memory_tiers (step 7) → decay + downgrade + forgotten
           → analyze_daily_tasks (step 8) → skill_proposals
           → weekly_interest_decay → run_decay() wire

Session 5 (later): Block 3 — Mood eval involved_people
           → Build dict from get_unmood_evaluated turns
           → Fix "# TODO" in _build_eval_context()

Session 6 (later): Block 6 — Attitude policy posture injection

Session 7 (later): Validate end-to-end
           → Mention a third party → nightly resolves/creates → interest
             evolves → diary references it → weekly decay cleans up inactives
```

After these sessions, Phase 4 is complete:
- Feature #1 (Perfil Viviente) — fully wired
- Feature #8 (Personalidad Dinámica) — mood + emotional honesty respond to social context
- Feature #9 (Memoria de Relaciones) — third parties recognized, relations inferred, injected
- Feature #13 (Curva de Olvido) — decay wired to scheduler

---

## Quick Reference — Key Files

| File | Does | Block |
|------|------|-------|
| `agent/cognition/stream.py:54` | `_entities_check()` — LLM extraction, called per turn | B1 ✅ |
| `agent/cognition/stream.py:144` | `cycle()` — orchestrator, passes entities to `build_messages()` | B1-2 |
| `agent/cognition/stream.py:106` | `_finalize_turn()` — saves turns + raw mentions | B1-2 |
| `agent/cognition/working_memory.py:57` | `_build_dynamic_suffix()` — **Block 1-2-4-6 target** | B1-6 |
| `agent/cognition/working_memory.py:89` | Commented-out user info/interest block | B1 |
| `agent/cognition/working_memory.py:130` | `build_messages()` — accepts `entities` param but ignores it | B1 |
| `agent/memory/mindstream/social.py:627` | `resolve_person_mention()` — entity resolution | B1 |
| `agent/memory/mindstream/social.py:829` | `add_delta()` — interest score deltas | B2 ✅ called from nightly |
| `agent/memory/mindstream/social.py:212` | `increment_person_mention()` — exists but no longer called from agent loop | — |
| `agent/memory/mindstream/social.py:bump_mention` | `bump_mention()` — nightly counter bump with explicit timestamp | B2 ✅ |
| `agent/memory/mindstream/social.py:874` | `run_decay()` — 28-day decay | B5 |
| `agent/memory/mindstream/social.py:910` | `infer_family_relations()` — 4 inference rules | B5 (update_relations) |
| `agent/memory/mindstream/consolidation.py:consolidate_entity_mentions` | Nightly step 1 — LLM resolves pending mentions | B2/B5 ✅ |
| `agent/memory/mindstream/consolidation.py:consolidate_person_interest` | Nightly step 2 — LLM evaluates deltas | B2 ✅ |
| `agent/memory/mindstream/mentions.py:12` | `add_mention()` — persist raw entities | B1 ✅ |
| `agent/memory/mindstream/mentions.py:get_pending` | Fetch all pending for nightly | B2 ✅ |
| `agent/memory/semantic.py:26` | `add_memory()` — Mem0 fact extraction (called from `consolidate_daily_memories` once wired) | B5 pending |
| `agent/memory/semantic.py:75` | `search_person_relevant()` — scoped Mem0 search | B1 |
| `agent/affect/evaluation.py:190` | `_build_eval_context()` — `"# TODO"` on line 211 | B3 |
| `agent/affect/evaluation.py:238` | `evaluate_mood()` — accepts `involved_people` | B3 |
| `agent/affect/mood.py:207` | `check_emotional_honesty_mode()` — sets flag | B4 |
| `agent/rhythm/routines/pulse.py:26` | `mood_check()` — passes `None` for involved_people | B3 |
| `agent/rhythm/routines/quiescence.py:consolidate_entity_mentions` | Step 1 — WIRED to consolidation.py impl | B2/B5 ✅ |
| `agent/rhythm/routines/quiescence.py:consolidate_person_interest` | Step 2 — WIRED to consolidation.py impl | B2 ✅ |
| `agent/rhythm/routines/quiescence.py:update_profiles` | Step 3 — stub `...` | B5 pending |
| `agent/rhythm/routines/quiescence.py:update_relations` | Step 4 — stub `...` | B5 pending |
| `agent/rhythm/routines/quiescence.py:consolidate_daily_memories` | Step 5 — stub `...` | B5 pending |
| `agent/rhythm/routines/quiescence.py:extract_daily_learnings` | Step 6 — WIRED | B5 ✅ |
| `agent/rhythm/routines/quiescence.py:cleanup_memory_tiers` | Step 7 — stub `...` | B5 pending |
| `agent/rhythm/routines/quiescence.py:analyze_daily_tasks` | Step 8 — stub `...` | B5 pending |
| `agent/rhythm/routines/forgetting.py:19` | `weekly_interest_decay()` — stub `...` | B5 pending |
| `agent/identity/principles/interest_policy.md` | Updated to nightly-batch design | B2 ✅ |
| `agent/identity/principles/memory_search.md` | 5-step search pipeline spec | B1 design |

---

## Test Specifications (from phase4A design doc)

Create `tests/test_social_known_persons.py` — no LLM, no Mem0. These tests validate the resolution engine before wiring to the prompt:

| # | Case | Expected |
|---|------|----------|
| 1 | Seed Jose | `get_known_person("jose")["display_name"] == "Jose Barco"`, `interest_score >= 0.70` |
| 2 | Alias exacto fuerte | `"Gloria Barco"` with confirmed alias → `resolved gloria1` |
| 3 | Primer nombre débil + una candidata relacionada | `"Gloria"` with `gloria1 mother_of jose` → `candidate_unconfirmed` |
| 4 | Primer nombre + varias candidatas | `"Gloria"` with `gloria1 mother_of jose` + `gloria2 coworker_of jose` → `ambiguous` |
| 5 | Descriptor relacional | `"mi mamá"` with `gloria1 mother_of jose` relation → `resolved` |
| 6 | Unknown | `"Marcela"` sin candidatos → `unknown` |
| 7 | Legacy wrappers | `get_user_information("jose")` returns `{profile: None, interest: ...}` |
| 8 | Working memory smoke test | `from agent.cognition.working_memory import build_messages` imports without error |

SQL manual checks after migrations/seeds:
```sql
-- Should include jose row
SELECT person_id, display_name, canonical_name_norm, interest_score, emotional_tone, status FROM known_persons;

-- Should return zero rows (old tables dropped or empty)
SELECT name FROM sqlite_master WHERE type='table' AND name IN ('person_interest', 'user_profiles');
```

---

## Risk Notes (from phase4A design doc)

1. **`working_memory.py` still imports legacy functions** — do NOT delete `create_person_interest`, `get_user_information`, `set_user_information`. They are live wrappers over `known_persons`.

2. **`run_decay()` was originally SQL-based** — rewritten in Python (`social.py:770`). No external SQL dependency.

3. **Old tables may still exist** — `person_interest` and `user_profiles` were never dropped via migration. The `002_create_core.sql` only creates new tables. If they exist from prior deploys, they're dead weight but harmless.

4. **Resolution by global name contaminates** — never return a person solely because their name matches. If no strong alias, strong descriptor, or anchored relation, return `candidate_unconfirmed`/`ambiguous`/`unknown`.

5. **`interest_score` is global (per-person, not per-owner)** — without `owner_user_id`, interest is Lumi's feeling toward that person globally. This is by design for now.
