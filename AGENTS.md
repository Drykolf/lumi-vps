# AGENTS.md — lumi-vps

## Package manager & Python

- **`uv`** is the package manager. Install deps: `uv sync`. Lockfile: `uv.lock`.
- Python >=3.12 required.
- Virtual env at `.venv/`. No pip/poetry.

## Project structure

```
agent/                     → Main FastAPI app "LUMI VPS" (v0.4.0)
mem0_server/               → Separate Mem0 REST API (Dockerized, port 8100)
```

### `agent/` directory layout

```
agent/
├── presence/app.py        → FastAPI entrypoint (root_path="/lumi")
├── cognition/             → Core agent loop
│   ├── attention.py       → Keyword pre-classifier (chat/web_search/long_task/explicit_save)
│   ├── stimulus.py        → Message handlers for each task type
│   ├── intention.py       → ToolRegistry (local + remote tools)
│   ├── stream.py          → Orchestrator: classify → dispatch → context → tool check → LLM → stream → save
│   └── working_memory.py  → System prompt builder (prefix + dynamic suffix)
├── expression/            → LLM abstraction layer
│   ├── synapses.py        → Factory with dual model groups + exponential backoff
│   └── providers/         → One class per model (BaseLLM ABC)
├── faculties/             → Tool implementations
│   ├── base.py            → BaseTool ABC
│   └── brave_search.py    → Brave Search API tool
├── affect/state.py        → Lumi's dynamic mood/emotion state (copied from lumi_state table)
├── memory/                → Memory subsystems (public API in __init__.py)
│   ├── episodic.py        → Conversation history (traces.db: save/query turns, mood/memory eval tracking)
│   ├── semantic.py        → Mem0 REST client (semantic memory via pgvector)
│   └── mindstream/        → Session, social, and consolidation modules
├── perception/websocket.py → MCP Bridge WebSocket (VPS ↔ PC)
├── rhythm/                → APScheduler — periodic maintenance jobs
│   ├── cadence.py         → Timing constants (15min tick, 7am daily, 3am nightly, Mon 4am weekly)
│   ├── heartbeat.py       → Job registration + scheduler start
│   ├── state.py           → Execution tracker (heartbeat_state / heartbeat_runs tables)
│   └── routines/          → Job implementations
├── subconscious/          → Singleton database access layer
│   ├── __init__.py        → traces + core singletons + init_databases()
│   ├── repositories/      → TracesRepository (traces.db) + CoreRepository (core.db)
│   ├── migrations/        → SQL schema files (idempotent)
│   └── seeds/             → Initial seed data
├── identity/              → Personality definition (read-only policy docs)
│   ├── lumi_soul.md       → Core personality (identity, voice, emotional architecture, moral compass)
│   ├── attitude.md        → Expressive framework (emotion tags, mood-to-attitude mapping)
│   └── principles/        → Behavioral rule docs (interest, memory, mood, reflection, relations, skills)
└── substrate/logger.py    → Shared logger with COL (UTC-5) timestamps
```

- `agent/` has **no `__init__.py`** — imports are absolute rooted from working dir: `from agent.cognition import attention`
- Entrypoint: `agent/presence/app.py` → FastAPI with `root_path="/lumi"`
- Mem0 entrypoint: `mem0_server/main.py` → FastAPI on container:8000, mapped to host:8100

## Running

- **No defined run command for the main app.** Presumably run with: `uvicorn agent.presence.app:app --host 0.0.0.0 --port 8000`
- **Neo4j is optional** — behind `--profile graph` in docker-compose. Only postgres + mem0 are required.
- Start services: `docker compose up` (add `--profile graph` for neo4j)

## Docker services

| Service   | Port (host) | Required? |
|-----------|-------------|-----------|
| postgres  | 5432        | yes       |
| mem0      | 8100        | yes       |
| neo4j     | 7474, 7687  | optional  |

- Postgres uses `ankane/pgvector:v0.5.1` image
- Caddy reverse proxy: `caddy/Caddyfile` routes `api.drykolf.xyz/lumi/*` → `localhost:8000`

## Environment

- Copy `.env.example` → `.env` and fill values
- `.env` is gitignored. `.env.example` is the template.
- Key env vars: `LUMI_API_KEY`, `DEEPINFRA_API_KEY`, `BRAVE_API_KEY`, `MEM0_ADMIN_API_KEY`, `POSTGRES_PASSWORD`, `NEO4J_PASSWORD`
- Mem0 config vars: `LLM_MODEL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMS`, `MEM0_LLM_MODEL`

## No tooling (yet)

- **No tests, no linter config, no formatter config, no typecheck, no CI.**
- No `Makefile`, `ruff.toml`, `mypy.ini`, `pyproject.toml` has no `[tool.*]` sections.
- If asked to add these, start from scratch including config files.

## LLM architecture

Two model groups with independent fallback chains. All via DeepInfra's OpenAI-compatible API (`DEEPINFRA_API_KEY`, base URL `https://api.deepinfra.com/v1/openai`).

### MAIN group (full conversation, tool use)

1. `Qwen/Qwen3.5-35B-A3B` (primary)
2. `stepfun-ai/Step-3.5-Flash` (fallback)
3. `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B` (fallback)

### LIGHTWEIGHT group (tool check, entity detection, memory extraction — ~200-500 tokens)

1. `mistralai/Mistral-Small-3.2-24B-Instruct-2506`
2. `deepseek-ai/DeepSeek-V4-Flash`
3. `Qwen/Qwen3.5-9B`

### Model-specific quirks (`extra_body`)

Each provider builds its own `_kwargs` (in `agent/expression/providers/`). When adding a new model, `extra_body` must match what the provider expects:

- **Qwen** (`Qwen3.5-35B-A3B`, `Qwen3.5-9B`): `extra_body={"top_k": 20, "chat_template_kwargs": {"enable_thinking": bool}}`
- **Step** (`Step-3.5-Flash`): `extra_body={"reasoning_effort": "none"}` (always)
- **Mistral, DeepSeek**: `extra_body={"reasoning_effort": "none"}` only when `thinking=False`
- **Nemotron**: no `extra_body` at all

The factory in `agent/expression/synapses.py` iterates model instances with exponential backoff (2 attempts per model: 2^0=1s, 2^1=2s) on `RateLimitError`. Fails over to next model after both attempts exhausted. Raises `RuntimeError("Todos los modelos están saturados.")` if all models fail.

## Agent loop (`agent/cognition/stream.py`)

```
classify (keyword router) → dispatch handler or → build context → tool check → LLM + stream → save
```

- Two entrypoints: `run()` (returns string) and `run_stream()` (async generator)
- `run_stream()` is what the `/v1/chat` endpoint uses
- Exactly 1 tool call per turn (lightweight LLM check before main generation — NOT iterative)
- `_finalize_turn()` saves both turns to traces.db, triggers session summarization every 5 turns

### Router (`agent/cognition/attention.py`)

Keyword-based pre-classifier (no embeddings). Returns: `chat`, `web_search`, `long_task`, `explicit_save`. Blocklist takes priority over web_search triggers. Also provides `detect_category()` for explicit saves (recipe, link, note, code, reference).

### Message handlers (`agent/cognition/stimulus.py`)

Dispatched by orchestrator for non-standard task types:

- **`long_task`**: Returns immediate acknowledgment ("Dame un momento...")
- **`explicit_save`**: LLM restructures message → saves to Mem0 via `save_explicit` → builds context → responds with verification
- **`web_search`**: Sets `metadata["web_search_needed"] = True` (tool check handles execution)

## Tools (`agent/cognition/intention.py`)

Two kinds:
- **Local** (VPS): registered via `register_tool(BaseTool)` — Brave Search is the only local tool. Schemas auto-generated from `BaseTool.schema()`.
- **Remote** (bridge): registered via `register_remote(name, schema)` — `get_clipboard` via WebSocket bridge.

Remote schemas overwrite local on collision. Tool execution: `_tool_check()` (lightweight LLM, ~500 tokens) decides if a tool is needed → `_formulate_query()` generates arguments → `intention.execute()` runs the tool.

## Memory architecture

### Database files

| Database | File | Purpose |
|----------|------|---------|
| Traces | `data/traces.db` | Conversation history, session turns, session summaries, heartbeat runs |
| Core   | `data/core.db` | Lumi's mood state, person interest, user profiles, relations, skill proposals, heartbeat state |

### Memory stores

| Store | Backend | Purpose |
|-------|---------|---------|
| Conversation history | SQLite (`data/traces.db`, via `agent/memory/episodic.py`) | Turn-by-turn, last N used in context |
| Semantic memory | Mem0 + pgvector (port 8100, via `agent/memory/semantic.py`) | Facts, people, persistent knowledge |
| Internal state | SQLite (`data/core.db`, via `agent/affect/state.py`) | Lumi's mood, energy, focus |

- `agent/memory/__init__.py` is the **public API** — stream.py and working_memory.py import from there. It re-exports from episodic, semantic, and mindstream submodules.
- Conversation history is NOT stored in Mem0 (by design — it's sequential, not semantic).
- `agent/memory/mindstream/social.py` manages person interest scores, user profiles, and relations in core.db.
- `agent/memory/mindstream/session.py` tracks turn counts per session (traces.db).
- `agent/memory/mindstream/consolidation.py` generates LLM-powered session summaries every 5 turns.

### Database access layer (`agent/subconscious/`)

Singleton pattern: `agent/subconscious/__init__.py` creates two module-level singletons:

```python
from agent.subconscious import traces, core
conn = traces.get_conn()   # → data/traces.db
conn = core.get_conn()     # → data/core.db
```

- `TracesRepository` and `CoreRepository` each manage their own SQLite connection + migration.
- `init_databases()` runs migrations (idempotent) + seeds. Called at startup.

## Personality

- System prompt built from two markdown files: `agent/identity/lumi_soul.md` (core personality) + `agent/identity/attitude.md` (expressive framework)
- Cached as system prompt prefix on first load (`_build_cached_prefix()` in `agent/cognition/working_memory.py`)
- Dynamic suffix appended per-turn: internal state, recent summaries, relevant memories, user profile, interest score
- Fallback (if both files missing): hardcoded brief Spanish prompt

## Internal state (`agent/affect/state.py`)

Lumi's dynamic mood stored as JSON blob in `core.db` → `lumi_state` table. Fields:

- `mood_valence` (-1.0 to 1.0), `mood_energy` (0.0 to 1.0), `irritation` (0.0 to 1.0), `focus_level` (0.0 to 1.0), `presence_need` (0.0 to 1.0)
- `state_label`, `state_sentence` — human-readable mood description
- `emotional_honesty_mode` — auto-enabled when irritation > 0.6, valence < -0.2, or presence_need > 0.6
- `morning_reset()` — daily regression toward baseline values (applied by rhythm system)

## Rhythm/heartbeat system (`agent/rhythm/`)

APScheduler-based periodic maintenance with 4 jobs (all COL/UTC-5 timezone):

| Job | Schedule | Purpose |
|-----|----------|---------|
| `rhythm_tick` | Every 15 min | Idle session check, pending summaries, mood evaluations |
| `daily_morning` | 7:00 AM daily | Morning mood regression (lerp toward baseline) |
| `daily_maintenance` | 3:00 AM daily | Nightly quiescence (stubs) |
| `weekly_decay` | Monday 4:00 AM | Weekly interest decay + forgetting (stubs) |

- `agent/rhythm/state.py` tracks execution in `heartbeat_state` (core.db) and `heartbeat_runs` (traces.db) tables
- Started at FastAPI `on_event("startup")` via `scheduler.start()` in `agent/presence/app.py`

## Skill/policy docs (identity/principles/)

Markdown files in `agent/identity/principles/` define Lumi's behavioral rules. They are **read-only policy documents**, not executable code:

- `interest_policy.md` — how interest_score evolves per person (deltas, caps, decay)
- `memory_policy.md` — what semantic data to store in Mem0 by interest level
- `memory_search.md` — 5-step memory search pipeline
- `mood_policy.md` — internal mood state fields, baselines, deltas, drift
- `reflection_policy.md` — 11-stage session close pipeline
- `relation_policy.md` — third-party relation storage and inference
- `skill_evolution.md` — automated skill proposal system (disabled first 90 days)

The SQL in `agent/subconscious/migrations/002_create_core.sql` defines the schema for person_interest, user_profiles, relations, lumi_state, skill_proposals, and heartbeat_state.

## Security

- `.env` contains live secrets. **Never commit it.** It is listed in `.gitignore`.
- API key auth: all endpoints require `X-Api-Key` header (checked via `verify_key`)
- Mem0 endpoints use a separate `MEM0_ADMIN_API_KEY` (X-API-Key header)
- WebSocket bridge auth uses query param `?api_key=...` (headers unavailable in WS handshake)

## Caddy

Production reverse proxy config at `caddy/Caddyfile`. Routes `/lumi/*` to the main FastAPI app on `localhost:8000`.
