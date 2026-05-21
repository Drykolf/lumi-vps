# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Start here, then read [AGENTS.md](AGENTS.md)** — it is the canonical deep-dive reference for subsystem internals, LLM model quirks, and behavioral policies.

## Commands

```bash
# Install dependencies (always use uv, never pip/poetry)
uv sync

# Start required services (PostgreSQL + Mem0)
docker compose up

# Start with optional Neo4j graph backend
docker compose --profile graph up

# Run the FastAPI app
uvicorn agent.presence.app:app --host 0.0.0.0 --port 8000

# Run tests (single test file exists)
uv run pytest tests/test_social_known_persons.py -v

# Run a single test
uv run pytest tests/test_social_known_persons.py::test_name -v
```

No linter, formatter, or type-checker is configured. If adding one, start from scratch.

## Architecture

lumi-vps is a personality-driven AI agent (LUMI) with three memory layers, a scheduled heartbeat, and a WebSocket bridge to a remote PC for tool access.

### Request flow

```
POST /v1/chat
  → stream.run_stream()
    → attention.classify()       # keyword router → chat/web_search/long_task/explicit_save
    → stimulus dispatch          # only for non-chat task types
    → working_memory.build()     # cached system prompt prefix + per-turn dynamic suffix
    → _tool_check()              # lightweight LLM (~500 tokens) decides if a tool is needed
    → main LLM (MAIN group)     # streams response
    → _finalize_turn()           # saves both turns to traces.db + entity extraction
```

Exactly **one tool call per turn** — the agent loop is not iterative.

### Memory layers

| Layer | Backend | Access |
|-------|---------|--------|
| Conversation history | `data/traces.db` (SQLite) | `agent/memory/episodic.py` |
| Semantic memory | Mem0 + pgvector (port 8100) | `agent/memory/semantic.py` |
| Internal state / social | `data/core.db` (SQLite) | `agent/affect/state.py`, `agent/memory/mindstream/social.py` |

`agent/memory/__init__.py` is the **public API** — always import from there, not from submodules directly.

### Database access

Singleton pattern. Never instantiate repositories directly:

```python
from agent.subconscious import traces, core
conn = traces.get_conn()   # data/traces.db
conn = core.get_conn()     # data/core.db
```

`init_databases()` (called at startup) runs all SQL migrations idempotently from `agent/subconscious/migrations/`.

### LLM groups

Two groups, both via DeepInfra's OpenAI-compatible API. Each has its own fallback chain:
- **MAIN** (Qwen3.5-35B → Step-3.5-Flash → Nemotron-120B): full conversation
- **LIGHTWEIGHT** (Mistral-Small → DeepSeek-V4-Flash → Qwen3.5-9B): tool check, entity detection, memory extraction

Each provider class in `agent/expression/providers/` sets model-specific `extra_body` kwargs — see AGENTS.md for the exact keys per provider before adding or modifying a model.

### Personality system

System prompt = cached prefix (built from `agent/identity/lumi_soul.md` + `agent/identity/attitude.md`) + per-turn dynamic suffix (mood state, diary entries, relevant memories, user profile).

Policy docs in `agent/identity/principles/` are **read-only behavioral rule documents** — they are embedded in prompts, not executed as code.

### Mood / affect

`agent/affect/state.py` maintains a JSON blob in `core.db.lumi_state`. Key fields: `mood_valence`, `mood_energy`, `irritation`, `focus_level`, `presence_need`, `negative_load` (0.0–1.0 accumulator).

`emotional_honesty_mode` uses hysteresis on `negative_load`: activates at ≥ 0.70, deactivates below 0.30.

### Scheduled jobs (APScheduler)

Four jobs registered at startup (`agent/rhythm/heartbeat.py`), all in COL/UTC-5:
- **Every 15 min**: mood evaluation, entity detection, idle decay
- **7 AM daily**: morning mood regression toward baseline
- **3 AM nightly**: quiescence — generates daily diary from conversation history
- **Monday 4 AM**: weekly interest decay

### Import conventions

`agent/` has **no `__init__.py`** at the top level. All imports are absolute from the working directory:
```python
from agent.cognition import attention   # correct
from .cognition import attention        # will fail
```
No hacer pruebas, no hacer comandos en consola, indicarq cuando necesite algo asi.