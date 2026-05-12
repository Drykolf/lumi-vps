# AGENTS.md — lumi-vps

## Package manager & Python

- **`uv`** is the package manager. Install deps: `uv sync`. Lockfile: `uv.lock`.
- Python >=3.12 required.
- Virtual env at `.venv/`. No pip/poetry.

## Project structure (two separate apps)

```
agent/           → Main FastAPI app "LUMI VPS" (v0.4.0)
mem0_server/     → Separate Mem0 REST API (Dockerized, port 8100)
```

- `agent/` has **no `__init__.py`** — imports are absolute rooted from working dir: `from agent.cognition import attention`
- Entrypoint: `agent/presence/app.py` → FastAPI with `root_path="/lumi"`
- Mem0 entrypoint: `mem0_server/main.py` → FastAPI on container:8000, mapped to host:8100

## Running

- **No defined run command for the main app.** The Mem0 Dockerfile shows the pattern: `uvicorn main:app --host 0.0.0.0 --port 8000`. Presumably run from `agent/` directory.
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

## No tooling (yet)

- **No tests, no linter config, no formatter config, no typecheck, no CI.**
- No `Makefile`, `ruff.toml`, `mypy.ini`, `pyproject.toml` has no `[tool.*]` sections.
- If asked to add these, start from scratch including config files.

## LLM architecture

Models are tried in priority order with exponential backoff on rate limits:

1. `Qwen/Qwen3.5-35B-A3B` (primary)
2. `stepfun-ai/Step-3.5-Flash` (fallback)
3. `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B` (fallback)

All via DeepInfra's OpenAI-compatible API (`DEEPINFRA_API_KEY`, base URL `https://api.deepinfra.com/v1/openai`).

### Model-specific quirks (`extra_body`)

- **Qwen**: uses `{"top_k": 20, "chat_template_kwargs": {"enable_thinking": bool}}`
- **Step**: uses `{"reasoning_effort": "none"}` — does NOT accept `chat_template_kwargs`
- **Nemotron**: no `extra_body` at all

The LLM factory in `agent/llm/factory.py` delegates to individual model classes. Each model class has its own `_kwargs` builder. When adding a new model, `extra_body` must match what the provider expects.

## Agent loop (`agent/cognition/stream.py`)

```
classify (keyword router) → build context → LLM + tools loop → stream → save
```

- Two entrypoints: `run` (returns string) and `run_stream` (async generator)
- `run_stream` is what the `/v1/chat` endpoint uses
- Max 10 tool-calling iterations per turn

### Router (`agent/cognition/attention.py`)

Keyword-based pre-classifier (no embeddings). Returns: `chat`, `web_search`, `long_task`, `explicit_save`. Blocklist takes priority over web_search triggers.

## Tools (`agent/cognition/intention.py`)

Two kinds:
- **Local** (VPS): registered via `register_tool(BaseTool)` — Brave Search is the only local tool
- **Remote** (bridge): registered via `register_remote(name, schema)` — `get_clipboard` via WebSocket bridge

Tool schemas: local tools auto-generate from function `__doc__`, remote tools provide explicit OpenAI schema. Remote schemas overwrite local on collision.

## Memory architecture

| Store | Backend | Purpose |
|-------|---------|---------|
| Conversation history | SQLite (`data/logs.db`) | Turn-by-turn, last N used in context |
| Semantic memory | Mem0 + pgvector (port 8100) | Facts, people, persistent knowledge |
| Internal state | SQLite (`data/core_state.db`) | Lumi's mood, energy, focus |

- `agent/memory/recall.py` is a **facade** — stream.py and working_memory.py import only from there. Real impl is in `agent/memory/semantic.py`.
- `agent/memory/episodic.py` exists but appears superseded by `semantic.py`.
- Conversation history is NOT stored in Mem0 (by design — it's sequential, not semantic).

## Personality

- SillyTavern v3 character card at `agent/identity/lumi_card.json`
- Cached as system prompt prefix on first load (`_build_cached_prefix()` in `agent/cognition/working_memory.py`)
- Fallback (if card missing): hardcoded brief Spanish prompt

## Skill/policy docs (identity/principles/)

Markdown files in `agent/identity/principles/` define Lumi's behavioral rules. They are **read-only policy documents**, not executable code. The SQL in `agent/subconscious/migrations/` defines schema for skill proposals and interest decay.

## Security

- `.env` contains live secrets. **Never commit it.** It is listed in `.gitignore`.
- API key auth: all endpoints require `X-Api-Key` header (checked via `verify_key`)
- Mem0 endpoints use a separate `MEM0_ADMIN_API_KEY` (X-API-Key header)
- WebSocket bridge auth uses query param `?api_key=...` (headers unavailable in WS handshake)

## Caddy

Production reverse proxy config at `caddy/Caddyfile`. Routes `/lumi/*` to the main FastAPI app on `localhost:8000`.
