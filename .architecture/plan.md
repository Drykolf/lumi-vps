# LUMI VPS — State & Plan

**Date:** May 11, 2026
**Active phase:** 4 (Mem0 + semantic memory)
**Next target:** Complete Phase 4

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
├── llm/                  # LLM layer
│   ├── factory.py        # model fallback (Qwen→Step→Nemotron)
│   ├── base.py           # BaseLLM ABC
│   ├── qwen3_5_35b.py
│   ├── step_3_5_flash.py
│   └── nemotron_super_120b.py
├── memory/               # Memory layer
│   ├── __init__.py         # single import point for agent (facade)
│   ├── semantic.py        # Mem0 REST API (add, search, explicit save)
│   ├── episodic.py        # conversation history + session tables
│   ├── mindstream/         # user state, session tracking, summaries
│   │   ├── social.py          # person_interest, user_profiles, relations
│   │   ├── session.py         # per-session turn counting
│   │   └── consolidation.py   # LLM-powered session summaries
├── bridge/               # (legacy bridge package, superseded by perception/)
├── affect/              # internal state (mood/energy/trust)
│   └── state.py
├── faculties/           # BaseTool + BraveSearch
├── rhythm/              # APScheduler (beat + idle check)
├── utils/                # shared logger (COL timezone)
├── identity/            # lumi_soul.md (58KB personality)
├── skills/               # policy documents (read-only)
└── schemas/              # SQLite databases
    ├── logs.db           # history + session_turns + session_summaries
    └── core_state.db     # person_interest, user_profiles, relations, lumi_state
```

---

## What Works (✅ Tested)

| System | Notes |
|--------|-------|
| **chat endpoint** | classify → handlers → context → tool check → LLM → stream |
| **explicit save** | "guarda esto" → LLM preprocessing → Mem0 with metadata.category |
| **web search tool** | Brave Search via keyword router + tool check |
| **tool check optimization** | Lightweight 200-token check replaces 10k-token full-context call — 65% savings |
| **session summaries** | Every 5 turns + 30min idle → LLM-generated, stored in SQLite |
| **scheduler heartbeat** | 5-min beat + 10-min idle session check |
| **auto-registration** | New user_id → person_interest row created on first chat |
| **user profiles** | JSON in SQLite (user_profiles), injected into context |
| **personality** | lumi_soul.md (58KB) loaded as system prefix |
| **internal state** | Numeric mood model (mood_policy.md compliant) — rewritten but NOT tested |
| **interest deltas + decay** | add_delta() with caps, run_decay() — implemented but NOT tested |
| **relations + family inference** | add_relation(), infer_family_relations() — implemented but NOT tested |
| **per-turn fact extraction** | add_memory() called after each normal chat turn |

---

## Phase 4 — Remaining Items

### 🔴 Core

| # | Item | What | Effort |
|---|------|------|--------|
| 1 | **Memory search pipeline** | 5-step pipeline from `memory_search.md`: entity resolution via `person_interest`, relation lookup via `relations`, semantic search with dedup, token-budgeted injection into context | Medium |
| 2 | ~~Per-turn fact extraction~~ | **DONE** — `add_memory()` called after each normal chat turn | — |

### 🟠 Validate (code exists, never tested)

| # | Item | How |
|---|------|-----|
| 3 | **Relations + family inference** | Exercise `add_relation()`, `infer_family_relations()` with real data |
| 4 | **Internal state** | Exercise `apply_deltas()`, `morning_reset()`, `check_emotional_honesty_mode()` |
| 5 | **Interest deltas + decay** | Verify `add_delta()` with caps, `run_decay()` runs correctly |

### 🟠 Wire up (code exists, not connected)

| # | Item | What |
|---|------|------|
| 6 | **Attitude policy injection** | Inject `attitude_policy.md` rules (score-driven posture, curiosity gate, reality filter) into system prompt |
| 7 | **Decay to scheduler** | Add `weekly_decay` job to APScheduler calling `run_decay()` |
| 8 | **Emotional honesty to context** | Wire `check_emotional_honesty_mode()` into `_build_dynamic_suffix()` |

### 🟡 Optional / Deferred

| # | Item |
|---|------|
| 9 | User profile periodic refresh from Mem0 facts |
| 10 | Reflection pipeline (11 stages from `reflection_policy.md`) |
| 11 | Passive observation (`/v1/observe` → Mem0) |
| 12 | Skill evolution (auto-proposals, disabled 90 days) |

---

## Implementation Order

```
Session 1: Memory search pipeline (#1)
           → Update context.py with entity resolution, relation lookup, dedup, token budget

Session 2: Validate (#3-5)
           → Test relations, internal state, interest deltas with real data

Session 3: Wire up (#6-8)
           → Attitude policy injection, decay to scheduler, emotional honesty to context

Session 4: Manual update
           → Fix paths, add new files, update Phase 4 status in LUMI-Manual.md
```

After these 4 sessions, Phase 4 is complete. The manual's feature catalog items #1 (Perfil Viviente), #7 (Arquitectura Modular), #8 (Personalidad Dinámica), #9 (Memoria de Relaciones) are fully implemented.

---

## Quick Reference — Key Files

| File | Does |
|------|------|
| `agent/cognition/stream.py` | Orchestrator — classify → dispatch → tool check → LLM → stream → save → extract |
| `agent/cognition/stimulus.py` | Message type handlers + explicit save processing + save verification |
| `agent/cognition/working_memory.py` | Builds system prompt (soul + state + summaries + memories + profile + interest) |
| `agent/cognition/attention.py` | Keyword classifier (chat/web_search/long_task/explicit_save) |
| `agent/memory/__init__.py` | Single import point for all memory operations |
| `agent/memory/semantic.py` | Mem0 REST API — add_memory, search_relevant, save_explicit |
| `agent/memory/episodic.py` | SQLite — history, session_turns, session_summaries |
| `agent/memory/mindstream/social.py` | SQLite — person_interest, user_profiles, relations, interest deltas |
| `agent/memory/mindstream/consolidation.py` | LLM session summary generation |
| `agent/memory/mindstream/session.py` | Per-session turn counting |
| `agent/llm/factory.py` | Model fallback orchestration (chat + chat_stream) |
| `agent/rhythm/heartbeat.py` | APScheduler — 5-min beat + 10-min idle check |
Proposed Plan
1. Per-turn flow — keep minimal (no changes needed)
The current cycle() already only does what's necessary: classify → build context → LLM reply → save turn. This stays as-is.
2. New hourly cron — Mood Policy
Create a new cron job at minute 0 of every hour that:
- Checks if interactions happened since last mood update
- If yes, computes mood deltas from recent turns (warmth signals, frustrations, etc.) and applies them
- If hour is ~7am (or first run after midnight), also runs morning_reset() regression toward baseline
- Deletes the existing daily_morning 7am cron entirely
Files to touch: agent/rhythm/heartbeat.py, possibly a new agent/affect/dynamics.py
3. Rewrite daily maintenance (3am) — full reflection pipeline
Wire up the reflection pipeline described in reflection_policy.md. This cron handles everything that was supposed to run at session close:
Stage	Policy	Implementation
Memory extraction	memory_policy.md	Batch-extract facts from recent sessions → Mem0
Apply interest deltas	interest_policy.md	Already tracked in session_delta; commit and reset
Relation inference	relation_policy.md	Call infer_family_relations()
Memory tier upgrades	memory_policy.md	Threshold-based upgrade/downgrade
Interest decay	interest_policy.md	Call run_decay()
Session summaries	reflection_policy.md	Summarize unprocessed sessions
User profile	reflection_policy.md	Refresh every 5 sessions
Skill evolution	skill_evolution.md	Pattern detection → drafts
Cleanup	reflection_policy.md	Clear Mem0 history, mark sessions closed
New file to create: agent/subconscious/reflection.py (or agent/memory/reflection.py) — implements the full pipeline orchestration.
4. Wire weekly cron (Mon 4am)
Simple — wire run_decay() into the existing weekly_decay stub.


