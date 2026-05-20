# LUMI VPS — Phase 4 Unified Plan

**Last updated:** May 21, 2026
**Source:** Merged from 3 sources:
- `.architecture/plan.md` (original Phase 4 plan)
- `.architecture/phase4_known_persons_read_path_plan.md` (Phase 4A — schema migration + social read-path)
- Full codebase audit of `agent/` (45 Python files)

**Active phase:** 4 (Mem0 + semantic memory — social features)
**Next target:** Block 2 — per-turn interest deltas

**Status:** Block 1 (read-path) shipped May 21, 2026. Per-turn third-party entity
resolution + injection is live. Mentions persist with resolution outcome for
nightly consolidation (Block 5). See `.claude/plans/i-need-to-start-sharded-eich.md`
for the design doc and decisions locked.

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
│   └── providers/                → 6 model providers (Qwen, Step, Nemotron, Mistral, DeepSeek, Qwen9B)
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
| **interest deltas** | ❌ `add_delta()` never called from agent loop | `social.py:725` |
| **person mention increments** | ✅ DONE 2026-05-21 — called in `_finalize_turn` for resolved | `social.py:212` |
| **interest decay** | ❌ `run_decay()` exists, weekly cron stub is `...` | `social.py:770`, `forgetting.py:19` |
| **relations (read)** | ✅ DONE 2026-05-21 — `get_relations()` called per resolved person | `social.py:303` |
| **relations (write)** | ❌ `add_relation()` not called in conversation flow (nightly only) | `social.py:243` |
| **family inference** | ❌ `infer_family_relations()` never triggered | `social.py:806` |
| **involved people in mood eval** | ❌ `mood_check()` passes `None`, `_build_eval_context()` still says `"# TODO"` | `pulse.py:74`, `evaluation.py:211` |
| **emotional honesty mode** | ❌ Flag set by `check_emotional_honesty_mode()` but never read by prompt builder | `mood.py:207`, NOT in `working_memory.py` |
| **nightly quiescence (4 of 6 subs)** | ❌ Stubs: consolidate_daily_memories, update_relationship_memory, analyze_daily_tasks, cleanup_memory_tiers | `quiescence.py:22-65` |
| **weekly interest decay** | ❌ `weekly_interest_decay()` is `...` | `forgetting.py:19` |
| **attitude policy injection** | ❌ Not started | |

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

### Block 2 — Per-Turn Interest Deltas (social feedback loop)

`add_delta()` has full logic (Jose floor 0.70, non-Jose cap 0.69) but the agent loop never calls it. Third parties are never registered as "mentioned" via `increment_person_mention()`.

**What to build:**
- After entity resolution in Block 1, for each resolved person:
  - Call `increment_person_mention(person_id)` (increments mention_count + last_mentioned)
  - Apply `add_delta()` based on the turn's emotional context:
    - Positive/warm interaction → `+0.002` to `+0.01`
    - Neutral → `0`
    - Negative/conflict → `-0.005` to `-0.02`
  - Non-Jose persons: delta accumulated into `session_delta` (capped at `+0.05` per session)
  - Note: `commit_session_close()` is currently a no-op (session_delta column doesn't exist)

**Files touched:** `agent/cognition/stream.py`, `agent/cognition/working_memory.py`

**Depends on:** Block 1 (needs resolved person_ids)

---

### Block 3 — Enrich Mood Evaluation with Involved People

`evaluate_mood()` in `evaluation.py` accepts `involved_people: dict | None` but `pulse.py:mood_check()` always passes `None`. The prompt says `"#Involved people:\n# TODO"`.

**What to build:**
- In `mood_check()` → build an `involved_people` dict from the session's unevaluated turns:
  - For each third party mentioned, bundle: `known_person` row + `relations`
- Pass it into `evaluate_mood(messages, current, involved_people=involved)`
- Fix `_build_eval_context()` line 211: replace `"# TODO"` with actual structured JSON

**Files touched:** `agent/rhythm/routines/pulse.py`, `agent/affect/evaluation.py`

**Depends on:** Block 1 (needs entity data from recent turns)

---

### Block 4 — Wire Emotional Honesty Mode into Context

`check_emotional_honesty_mode()` sets `emotional_honesty_mode` flag on Lumi's state when thresholds are crossed (irritation > 0.6, valence < -0.2, or presence_need > 0.6). But nothing reads this flag to change Lumi's behavior.

**What to build:**
- In `_build_dynamic_suffix()`, read the `emotional_honesty_mode` flag from `get_state()`
- If `True`, inject into the dynamic block:
  ```
  [Modo de honestidad emocional activo]
  Lumi responde con franqueza directa, sin suavizar sus opiniones.
  Prioriza claridad sobre cortesía. No oculta irritación ni desagrado.
  ```
- If `False`, no injection (normal behavior via lumi_soul.md)

**Files touched:** `agent/cognition/working_memory.py`

**Depends on:** nothing — `get_state()` already returns the flag

---

### Block 5 — Wire Stubs to Real Code

Three cron jobs exist in APScheduler but their implementations are partially empty:

#### 5a — Weekly interest decay (`forgetting.py:19`)
```python
# Current: ...
# Fix:
from agent.memory import run_decay
run_decay()  # Already implemented in social.py:770
```
Also wire `decay_inactive_people()` and `forget_stale_people()` if needed.

#### 5b — Nightly quiescence (`quiescence.py` — 4 of 6 subs are stubs)

| Sub-function | What to implement | Status |
|--------------|-------------------|--------|
| `consolidate_daily_memories()` | Batch-extract facts from unprocessed turns → Mem0 via lightweight LLM | ❌ `...` |
| `update_relationship_memory()` | Call `infer_family_relations()` + detect new relation patterns from recent turns | ❌ `...` |
| `update_user_profiles()` | No-op: table removed, migrated to known_persons + Mem0 | ✅ `pass` |
| `analyze_daily_tasks()` | Detect pending tasks mentioned in turns → store in `skill_proposals` table | ❌ `...` |
| `extract_daily_learnings()` | Generate diary entries via `generate_daily_diary()` | ✅ WIRED |
| `cleanup_memory_tiers()` | Demote inactive persons below thresholds, delete `status='forgotten'` after grace period | ❌ `...` |

**Files touched:** `agent/rhythm/routines/forgetting.py`, `agent/rhythm/routines/quiescence.py`

**Depends on:** Block 1 (nightly subs need entity data from daily turns)

---

### Block 6 — Attitude Policy Dynamic Injection

`attitude.md` is loaded into the cached prefix alongside `lumi_soul.md`, but the dynamic rules (score-driven posture, curiosity gate, reality filter) are not injected per-turn based on current context.

**What to build:**
- In `_build_dynamic_suffix()`, inject 1-2 line summaries based on context:
  - If any mentioned person has `interest_score < 0.10` → `"[Postura] Persona con bajo interés. Respuestas neutras, sin calidez extra."`
  - If any mentioned person has `interest_score < 0` → `"[Postura] Persona en zona negativa. Respuestas mínimas, formales, sin apertura personal."`
  - If `emotional_honesty_mode` is active → `"[Postura] Modo honesto: franqueza sobre diplomacia."`

**Files touched:** `agent/cognition/working_memory.py`

**Depends on:** Block 1 (needs interest scores), Block 4 (needs emotional honesty flag)

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
Session 1: Block 1 — Complete entity recognition pipeline ✅ SHIPPED 2026-05-21
           → resolve_person_mention() wired in stream._resolve_entities()
           → search_person_relevant() called per resolved person
           → "Personas mencionadas" block + [Posibles]/[Ambiguas]/[Sin perfil] sections
           → Speaker block driven by get_known_person() (replaced legacy stub)
           → mentions stamped with resolution outcome for nightly consolidation

Session 2: Block 2 — Per-turn interest deltas
           → Wire increment_person_mention() + add_delta() into _finalize_turn()
           → Wire commit_session_close() at session end (or make it meaningful)

Session 3: Blocks 3 + 4 — Mood eval enrichment + emotional honesty
           → Build involved_people dict for mood_check()
           → Fix "# TODO" in _build_eval_context()
           → Inject emotional honesty flag into dynamic suffix
           → Wire add_memory() fact extraction per turn

Session 4: Block 5 — Wire stubs
           → weekly_interest_decay() → call run_decay()
           → Nightly quiescence subs (consolidation, relations, tasks, cleanup_tiers)
           → (extract_daily_learnings already wired)

Session 5: Block 6 — Attitude policy injection
           → Per-turn posture hints based on interest scores

Session 6: Validate with real data
           → Test full pipeline: mention a third party → entity created →
             relations built → interest evolves → mood reflects it →
             decay cleans up inactive persons
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
| `agent/memory/mindstream/social.py:725` | `add_delta()` — interest score deltas | B2 |
| `agent/memory/mindstream/social.py:212` | `increment_person_mention()` — mention counter | B2 |
| `agent/memory/mindstream/social.py:770` | `run_decay()` — 28-day decay | B5 |
| `agent/memory/mindstream/social.py:806` | `infer_family_relations()` — 4 inference rules | B5 |
| `agent/memory/mindstream/mentions.py:12` | `add_mention()` — persist raw entities | B1 ✅ |
| `agent/memory/semantic.py:26` | `add_memory()` — Mem0 fact extraction (never called) | ADD |
| `agent/memory/semantic.py:75` | `search_person_relevant()` — scoped Mem0 search | B1 |
| `agent/affect/evaluation.py:190` | `_build_eval_context()` — `"# TODO"` on line 211 | B3 |
| `agent/affect/evaluation.py:238` | `evaluate_mood()` — accepts `involved_people` | B3 |
| `agent/affect/mood.py:207` | `check_emotional_honesty_mode()` — sets flag | B4 |
| `agent/rhythm/routines/pulse.py:26` | `mood_check()` — passes `None` for involved_people | B3 |
| `agent/rhythm/routines/quiescence.py:22` | `consolidate_daily_memories()` — stub `...` | B5 |
| `agent/rhythm/routines/quiescence.py:26` | `update_relationship_memory()` — stub `...` | B5 |
| `agent/rhythm/routines/quiescence.py:35` | `analyze_daily_tasks()` — stub `...` | B5 |
| `agent/rhythm/routines/quiescence.py:39` | `extract_daily_learnings()` — **WIRED** | B5 ✅ |
| `agent/rhythm/routines/quiescence.py:64` | `cleanup_memory_tiers()` — stub `...` | B5 |
| `agent/rhythm/routines/forgetting.py:19` | `weekly_interest_decay()` — stub `...` | B5 |
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
