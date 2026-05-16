# LUMI VPS — State & Plan

**Date:** May 15, 2026
**Active phase:** 4 (Mem0 + semantic memory — social features)
**Next target:** Third-party entity recognition → per-turn social feedback loop

---

## Current Architecture

```
agent/
├── presence/             # FastAPI entrypoint
│   └── app.py            # main FastAPI app (root_path="/lumi")
├── perception/           # External world sensing
│   └── websocket.py      # WebSocket bridge VPS↔PC
├── cognition/            # Orchestration
│   ├── stream.py          # cycle() unified orchestrator
│   ├── stimulus.py        # message type handlers + explicit save processing
│   ├── working_memory.py  # prompt builder (lumi_soul.md + dynamic suffix)
│   ├── attention.py       # keyword classifier
│   └── intention.py       # tool registry + dispatch
├── expression/           # LLM layer (synapses.py factory + providers/)
│   ├── synapses.py       # Model fallback (Qwen→Step→Nemotron)
│   └── providers/        # One class per model
├── memory/               # Memory layer
│   ├── __init__.py         # single import point for agent (facade)
│   ├── semantic.py        # Mem0 REST API (add, search, explicit save)
│   ├── episodic.py        # conversation history + session tables
│   ├── mindstream/         # user state, session tracking, summaries
│   │   ├── social.py          # person_interest, user_profiles, relations
│   │   ├── session.py         # per-session turn counting
│   │   └── consolidation.py   # LLM-powered session summaries
├── affect/               # internal state (mood/energy/focus/irritation)
│   ├── state.py          # mood model, morning_reset, emotional_honesty_mode
│   └── evaluation.py     # idle decay + LLM mood evaluation
├── faculties/            # BaseTool + BraveSearch
├── rhythm/               # APScheduler (15min tick + 4 cron jobs)
│   ├── heartbeat.py      # Job registration + scheduler start
│   ├── cadence.py        # Timing constants
│   ├── state.py          # Execution tracker (heartbeat_state / heartbeat_runs)
│   └── routines/         # Job implementations
│       ├── pulse.py       # rhythm_tick (15min)
│       ├── morning.py     # daily_morning (7am)
│       ├── quiescence.py  # nightly_quiescence (3am) — STUBS
│       └── forgetting.py  # weekly_forgetting (Mon 4am) — STUBS
├── identity/             # lumi_soul.md + attitude.md + principles/
│   └── principles/        # Policy docs (memory_search.md, interest_policy.md, etc.)
├── subconscious/          # Singleton DB layer (traces.db + core.db)
└── substrate/            # Shared logger (COL timezone)
```

---

## What Works (code exists and is wired)

| System | Notes |
|--------|-------|
| **chat endpoint** | classify → handlers → context → tool check → LLM → stream |
| **explicit save** | "guarda esto" → LLM preprocessing → Mem0 with metadata.category |
| **web search tool** | Brave Search via keyword router + tool check |
| **tool check optimization** | Lightweight 200-token check — 65% savings over full-context call |
| **session summaries** | Every 5 turns + 30min idle → LLM-generated, stored in SQLite |
| **scheduler heartbeat** | 15min tick (idle sessions, summaries, mood), 7am morning, 3am nightly, Mon 4am weekly |
| **auto-registration** | New user_id → person_interest row created on first chat |
| **user profiles** | JSON in SQLite (user_profiles), injected into context |
| **personality** | lumi_soul.md + attitude.md loaded as cached system prefix |
| **internal state** | Numeric mood model (valence, energy, focus, irritation, presence_need) |
| **idle decay** | Deterministic per-hour decay toward floors/caps, applied on scheduler tick |
| **morning reset** | 7am regression toward baseline (lerp) via APScheduler |
| **mood evaluation** | Hourly LLM eval via lightweight model (LIGHTWEIGHT group) |
| **per-turn fact extraction** | add_memory() called after each normal chat turn |

## Code exists but is NOT wired / NOT tested

| System | Status |
|--------|--------|
| **interest deltas** | `add_delta()` with caps (Jose floor 0.70, non-Jose cap 0.69). Never called from agent loop. |
| **interest decay** | `run_decay()` uses interest_decay.sql. Weekly cron stub doesn't call it. |
| **relations** | `add_relation()`, `get_relations()`, `get_relation_between()`. Never called in conversation flow. |
| **family inference** | `infer_family_relations()` with 4 rules. Never triggered. |
| **entity detection** | `_memory_check()` LLM call exists in working_memory.py. Never called. |
| **involved people in mood eval** | `evaluate_mood()` accepts `involved_people` param but always receives None. |
| **emotional honesty mode** | `check_emotional_honesty_mode()` sets flag on state. Never read by prompt builder. |
| **nightly quiescence** | 6 sub-functions all empty `...` stubs. |
| **weekly forgetting** | `weekly_interest_decay()` is empty `...`. Cleanup sub is wired but decay is not. |

---

## Phase 4 — Remaining Work (6 blocks)

### Block 1 — Third-Party Entity Recognition (unlocks everything social)

The `memory_search.md` 5-step pipeline is fully specified but **zero steps are connected** to the agent loop. The entry point — `_memory_check()` — exists but is never called.

**What to build** — wire the pipeline into `_build_dynamic_suffix()`:

| Step | Action | Source |
|------|--------|--------|
| 1 | Call `_memory_check(message, sid)` per turn | `working_memory.py:48` (exists) |
| 2 | Entity resolution: for each detected name, call `find_user_id_by_name()` | `social.py:247` (exists) |
| 3 | Miss → seed `create_person_interest(name, score=0.10)` | `social.py:46` (exists) |
| 4 | Hit → load `person_interest` row + `get_relations(person_id)` | `social.py:64, :289` (exists) |
| 5 | Scoped Mem0 search: `search_relevant()` filtered to `metadata.person_id=X` | `semantic.py` (exists) |
| 6 | Dedup against last 10 turns in history | `episodic.py` (exists) |
| 7 | Token-budgeted injection: `"Personas mencionadas: ..."` block | new formatting |

**Format target:**
```
Personas mencionadas en este turno:
- Gloria (interes 0.62, tono calido): madre de Jose. Estudia enfermeria.
  Ultima mencion: hace 4 dias. Relacion: family.
- Carlos_jefe (interes 0.45, tono complejo): jefe en Inmobarco.
  Relacion: profesional.

Memoria relevante:
- Gloria recibio buenas notas en su parcial de farmacologia en mayo 2026.
```

**Files touched:** `agent/cognition/working_memory.py` (primary)

**Depends on:** nothing — all building blocks exist

---

### Block 2 — Per-Turn Interest Deltas (social feedback loop)

`add_delta()` has full logic (Jose floor, non-Jose cap, session delta tracking, status recalculation) but the agent loop never calls it. Third parties are never registered as "mentioned."

**What to build:**
- After `_finalize_turn()` in `stream.py`, if Block 1 detected third parties:
  - Call `_increment_mention(person_id)` for each detected person
  - Apply a small `add_delta()` based on the turn's emotional context:
    - Positive/warm interaction → `+0.002` to `+0.01`
    - Neutral → `0`
    - Negative/conflict → `-0.005` to `-0.02`
  - Non-Jose persons: delta accumulated into `session_delta` (capped at `+0.05` per session)
- Call `commit_session_close()` at session end (resets all `session_delta` to 0)

**Files touched:** `agent/cognition/stream.py`, `agent/cognition/working_memory.py`

**Depends on:** Block 1 (needs resolved person_ids)

---

### Block 3 — Enrich Mood Evaluation with Involved People

`evaluate_mood()` in `evaluation.py` accepts `involved_people: dict | None` but `pulse.py:mood_check()` always passes `None`. The prompt literally says `"#Involved people:\n# TODO"`.

**What to build:**
- In `mood_check()` → build an `involved_people` dict from the session's unevaluated turns:
  - For each third party mentioned, bundle: `person_interest` row + `user_profile` + `relations`
- Pass it into `evaluate_mood(messages, current, involved_people=involved)`
- Fix `_build_eval_context()` line 211: replace `"# TODO"` with actual structured JSON

This lets the LLM mood evaluator understand *who* Lumi was interacting with, not just *what* was said. Unknown third parties affect `irritation` more than `mood_valence` (per the prompt rules), but only if the LLM knows they exist.

**Files touched:** `agent/rhythm/routines/pulse.py`, `agent/affect/evaluation.py`

**Depends on:** Block 1 (needs entity data from recent turns)

---

### Block 4 — Wire Emotional Honesty Mode into Context

`check_emotional_honesty_mode()` sets a boolean flag on Lumi's internal state when thresholds are crossed (irritation > 0.6, valence < -0.2, or presence_need > 0.6). But nothing reads this flag to change Lumi's behavior.

**What to build:**
- In `_build_dynamic_suffix()`, read the `emotional_honesty_mode` flag
- If `True`, inject into the dynamic block:
  ```
  [Modo de honestidad emocional activo]
  Lumi responde con franqueza directa, sin suavizar sus opiniones.
  Prioriza claridad sobre cortesia. No oculta irritacion ni desagrado.
  ```
- If `False`, no injection (normal behavior via lumi_soul.md)

**Files touched:** `agent/cognition/working_memory.py`

**Depends on:** nothing — `get_state()` already returns the flag

---

### Block 5 — Wire Stubs to Real Code

Three cron jobs exist in APScheduler but their implementations are empty:

#### 5a — Weekly interest decay (`forgetting.py:19`)
```python
# Current: ...
# Fix:
from agent.memory import run_decay
run_decay()  # Already implemented in social.py:205 — SQL script with 28-day threshold
```

#### 5b — Nightly quiescence (`quiescence.py` — all 6 subs empty)

| Sub-function | What to implement |
|--------------|-------------------|
| `consolidate_daily_memories()` | Batch-extract facts from unprocessed turns → Mem0 via lightweight LLM |
| `update_relationship_memory()` | Call `infer_family_relations()` + detect new relation patterns from recent turns |
| `update_user_profiles()` | LLM review of recent session summaries → update profile JSON via `set_user_information()` |
| `analyze_daily_tasks()` | Detect pending tasks mentioned in turns → store in `skill_proposals` table |
| `extract_daily_learnings()` | Pattern detection from conversations → draft skill proposals |
| `cleanup_memory_tiers()` | Demote inactive persons below thresholds, delete `status='forgotten'` after grace period |

**Files touched:** `agent/rhythm/routines/forgetting.py`, `agent/rhythm/routines/quiescence.py`

**Depends on:** Block 1 (nightly subs need entity data from daily turns)

---

### Block 6 — Attitude Policy Dynamic Injection

`attitude.md` is loaded into the cached prefix alongside `lumi_soul.md`, but the dynamic rules (score-driven posture, curiosity gate, reality filter) are not injected per-turn based on current context.

**What to build:**
- In `_build_dynamic_suffix()`, inject 1-2 line summaries based on context:
  - If any mentioned person has `interest_score < 0.10` → `"[Postura] Persona con bajo interes. Respuestas neutras, sin calidez extra."`
  - If any mentioned person has `interest_score < 0` → `"[Postura] Persona en zona negativa. Respuestas minimas, formales, sin apertura personal."`
  - If `emotional_honesty_mode` is active → `"[Postura] Modo honesto: franqueza sobre diplomacia."`

**Files touched:** `agent/cognition/working_memory.py`

**Depends on:** Block 1 (needs interest scores), Block 4 (needs emotional honesty flag)

---

## Implementation Order

```
Session 1: Block 1 — Third-party entity recognition
           → Call _memory_check() → resolve entities → scoped Mem0 → inject
           → This is the bottleneck. Everything else feeds from here.

Session 2: Block 2 — Per-turn interest deltas
           → Wire _increment_mention() + add_delta() into stream.py
           → Wire commit_session_close() at session end

Session 3: Blocks 3 + 4 — Mood eval enrichment + emotional honesty
           → Build involved_people dict for mood_check
           → Inject emotional honesty flag into dynamic suffix
           → (Can be done in parallel with Session 2)

Session 4: Block 5 — Wire stubs
           → weekly_interest_decay() → call run_decay()
           → Nightly quiescence subs (consolidation, relations, profiles)

Session 5: Block 6 — Attitude policy injection
           → Per-turn posture hints based on interest scores

Session 6: Validate with real data
           → Test full pipeline: mention a third party → entity created →
             relations built → interest evolves → mood reflects it →
             decay cleans up inactive persons
```

After these sessions, Phase 4 is complete:
- Feature #1 (Perfil Viviente) — fully wired
- Feature #8 (Personalidad Dinamica) — mood + emotional honesty respond to social context
- Feature #9 (Memoria de Relaciones) — third parties recognized, relations inferred, injected
- Feature #13 (Curva de Olvido) — decay wired to scheduler

---

## Quick Reference — Key Files

| File | Does |
|------|------|
| `agent/cognition/stream.py` | Orchestrator — classify → dispatch → tool check → LLM → stream → save |
| `agent/cognition/working_memory.py` | System prompt builder — soul + state + summaries + memories + **Block 1-2-4-6 target** |
| `agent/cognition/attention.py` | Keyword classifier (chat/web_search/long_task/explicit_save) |
| `agent/memory/__init__.py` | Single import point for all memory operations |
| `agent/memory/semantic.py` | Mem0 REST API — add_memory, search_relevant, save_explicit |
| `agent/memory/mindstream/social.py` | person_interest, user_profiles, relations, add_delta, run_decay, infer_family_relations |
| `agent/memory/mindstream/consolidation.py` | LLM session summary generation |
| `agent/affect/evaluation.py` | Idle decay + LLM mood evaluation — **Block 3 target** |
| `agent/affect/state.py` | Internal state CRUD, morning_reset, emotional_honesty_mode |
| `agent/rhythm/heartbeat.py` | APScheduler job registration |
| `agent/rhythm/routines/pulse.py` | 15min tick — idle sessions, summaries, mood check — **Block 3 target** |
| `agent/rhythm/routines/quiescence.py` | Nightly maintenance stubs — **Block 5 target** |
| `agent/rhythm/routines/forgetting.py` | Weekly decay stub — **Block 5 target** |
| `agent/identity/principles/memory_search.md` | 5-step search pipeline spec — **Block 1 design doc** |
