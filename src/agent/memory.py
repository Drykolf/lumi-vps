"""
Interfaz pública de memoria — Fase 4+.
loop.py y context.py solo importan este módulo.
Implementaciones en src/memory/mem0_client.py y src/memory/core_state.py
"""
from src.memory.mem0_client import (
    init_db,
    save_turn,
    get_history,
    search_relevant,
    add_memory,
    get_profile,
    set_profile,
    save_explicit,
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

__all__ = [
    "init_db",
    "init_core_db",
    "save_turn",
    "get_history",
    "search_relevant",
    "add_memory",
    "get_profile",
    "set_profile",
    "save_explicit",
    "add_memory_explicit",
    "get_person",
    "find_person_by_name",
    "create_person",
    "add_delta",
    "commit_session_close",
    "run_decay",
    "get_relations",
    "add_relation",
    "infer_family_relations",
]