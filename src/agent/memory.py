"""
Interfaz pública de memoria — Fase 4.
loop.py y context.py solo importan este módulo.
La implementación real está en src/memory/mem0_client.py
"""
from src.memory.mem0_client import (
    init_db,
    save_turn,
    get_history,
    search_relevant,
    add_memory,
    get_profile,
    set_profile,
)

__all__ = [
    "init_db",
    "save_turn",
    "get_history",
    "search_relevant",
    "add_memory",
    "get_profile",
    "set_profile",
]