"""
Public API for memory — all agent modules import from here.

Underlying implementations:
  agent/memory/episodic.py       — historial, sesiones, resumenes (traces.db)
  agent/memory/semantic.py       — Mem0 semantico
  agent/memory/mindstream/social.py         — personas, relaciones, lumi_state (core.db)
  agent/memory/mindstream/session.py        — contador de turnos por sesion (traces.db)
  agent/memory/mindstream/consolidation.py  — generacion LLM de resumenes de sesion (traces.db)

Usage:
    from agent.memory import get_history, save_turn, add_memory, ...
"""
from agent.subconscious import init_databases
from agent.memory.episodic import (
    save_turn,
    get_history,
    get_session_turns,
    get_recent_session_history,
    mark_summarized,
    get_unmood_evaluated,
    mark_mood_evaluated,
    get_unmemory_evaluated,
    mark_memory_evaluated,
)
from agent.memory.semantic import (
    search_relevant,
    search_person_relevant,
    add_memory,
    save_explicit,
)

# Alias: loop.py expects add_memory_explicit per memory_policy.md naming
add_memory_explicit = save_explicit
from agent.memory.mindstream.social import (
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
    get_known_person,
    ensure_known_person,
    update_known_person,
    increment_person_mention,
    list_active_known_persons,
    normalize_name,
    parse_aliases,
    build_alias,
    add_person_alias,
    find_person_candidates_by_name,
    resolve_person_mention,
    find_related_persons,
    PersonMention,
    PersonCandidate,
    PersonResolution,
    ResolutionStatus,
)
from agent.memory.mindstream.session import record_turn, get_session_users, reset_turns, get_stale_sessions
from agent.memory.mindstream.consolidation import generate_summary, get_recent_summaries
from agent.memory.mindstream.cleanup import cleanup_history, cleanup_summaries, cleanup_heartbeat_runs, run_all_cleanups
from agent.memory.mindstream.mentions import (
    add_mention,
    get_recent_mentions,
    get_user_mentions,
)

# Backward compat alias
get_profile = get_user_information

__all__ = [
    "init_databases",
    "init_core_db",
    "save_turn",
    "get_history",
    "get_session_turns",
    "get_recent_session_history",
    "mark_summarized",
    "get_unmood_evaluated",
    "mark_mood_evaluated",
    "get_unmemory_evaluated",
    "mark_memory_evaluated",
    "search_relevant",
    "search_person_relevant",
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
    "get_known_person",
    "ensure_known_person",
    "update_known_person",
    "increment_person_mention",
    "list_active_known_persons",
    "normalize_name",
    "parse_aliases",
    "build_alias",
    "add_person_alias",
    "find_person_candidates_by_name",
    "resolve_person_mention",
    "find_related_persons",
    "PersonMention",
    "PersonCandidate",
    "PersonResolution",
    "ResolutionStatus",
    "record_turn",
    "get_session_users",
    "reset_turns",
    "get_stale_sessions",
    "generate_summary",
    "get_recent_summaries",
    "cleanup_history",
    "cleanup_summaries",
    "cleanup_heartbeat_runs",
    "run_all_cleanups",
    "add_mention",
    "get_recent_mentions",
    "get_user_mentions",
]
