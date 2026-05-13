"""
Interfaz publica de memoria — Fase 4+.
loop.py y context.py solo importan este modulo.

Implementaciones:
  agent/memory/episodic.py     — historial, sesiones, resumenes (traces.db)
  agent/memory/semantic.py     — Mem0 semantico
  agent/memory/social.py       — personas, relaciones, lumi_state (core.db)
  agent/memory/session.py      — contador de turnos por sesion (traces.db)
  agent/memory/consolidation.py — generacion LLM de resumenes de sesion (traces.db)
"""
from agent.subconscious import init_databases
from agent.memory.episodic import (
    save_turn,
    get_history,
    get_session_turns,
    mark_summarized,
    get_unmood_evaluated,
    mark_mood_evaluated,
    get_unmemory_evaluated,
    mark_memory_evaluated,
)
from agent.memory.semantic import (
    search_relevant,
    add_memory,
    save_explicit,
)

# Alias: loop.py expects add_memory_explicit per memory_policy.md naming
add_memory_explicit = save_explicit
from agent.memory.social import (
    init_core_db,
    get_user_information,
    set_user_information,
    create_person_interest,
    add_delta,
    commit_session_close,
    run_decay,
    get_relations,
    add_relation,
    infer_family_relations,
    find_user_id_by_name,
)
from agent.memory.session import record_turn, get_session_users, reset_turns, get_stale_sessions
from agent.memory.consolidation import generate_summary, get_recent_summaries

# Backward compat alias
get_profile = get_user_information

__all__ = [
    "init_databases",
    "init_core_db",
    "save_turn",
    "get_history",
    "get_session_turns",
    "mark_summarized",
    "get_unmood_evaluated",
    "mark_mood_evaluated",
    "get_unmemory_evaluated",
    "mark_memory_evaluated",
    "search_relevant",
    "add_memory",
    "get_user_information",
    "set_user_information",
    "create_person_interest",
    "save_explicit",
    "add_memory_explicit",
    "add_delta",
    "commit_session_close",
    "run_decay",
    "get_relations",
    "add_relation",
    "infer_family_relations",
    "find_user_id_by_name",
    "record_turn",
    "get_session_users",
    "reset_turns",
    "get_stale_sessions",
    "generate_summary",
    "get_recent_summaries",
]