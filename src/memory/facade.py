"""
Interfaz publica de memoria — Fase 4+.
loop.py y context.py solo importan este modulo.

Implementaciones:
  src/memory/sqlite_memory.py    — historial, sesiones, resumenes (SQLite)
  src/memory/mem0_client.py      — Mem0 semantico
  src/memory/core_state.py       — personas, relaciones, lumi_state
  src/memory/session_tracker.py  — contador de turnos por sesion
  src/memory/summary.py          — generacion LLM de resumenes de sesion
"""
from src.memory.sqlite_memory import (
    init_db,
    save_turn,
    get_history,
    get_session_turns,
    mark_summarized,
)
from src.memory.mem0_client import (
    search_relevant,
    add_memory,
    get_profile,
    set_profile,
    save_explicit,
    process_explicit_memory,
)

# Alias: loop.py expects add_memory_explicit per memory_policy.md naming
add_memory_explicit = save_explicit
from src.memory.core_state import (
    init_core_db,
    get_person,
    find_person_by_name,
    create_person,
    add_delta,
    commit_session_close,
    run_decay,
    get_relations,
    add_relation,
    infer_family_relations,
)
from src.memory.session_tracker import record_turn, get_session_users, reset_turns, get_stale_sessions
from src.memory.summary import generate_summary, get_recent_summaries

__all__ = [
    "init_db",
    "init_core_db",
    "save_turn",
    "get_history",
    "get_session_turns",
    "mark_summarized",
    "search_relevant",
    "add_memory",
    "get_profile",
    "set_profile",
    "save_explicit",
    "add_memory_explicit",
    "process_explicit_memory",
    "get_person",
    "find_person_by_name",
    "create_person",
    "add_delta",
    "commit_session_close",
    "run_decay",
    "get_relations",
    "add_relation",
    "infer_family_relations",
    "record_turn",
    "get_session_users",
    "reset_turns",
    "get_stale_sessions",
    "generate_summary",
    "get_recent_summaries",
]