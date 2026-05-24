"""
Public API for memory — all agent modules import from here.

Underlying implementations:
  agent/memory/episodic.py       — historial, sesiones, resumenes (traces.db)
  agent/memory/semantic.py       — Mem0 semantico
  agent/memory/mindstream/social.py         — personas, relaciones, lumi_state (core.db)
  agent/memory/mindstream/session.py        — contador de turnos por sesion (traces.db)
  agent/memory/mindstream/consolidation.py  — generacion LLM de resumenes de sesion (traces.db)

Usage:
    from agent.memory import get_recent_user_log, save_turn, add_memory, ...
"""
from agent.subconscious import init_databases
from agent.memory.episodic import (
    save_turn,
    get_recent_session_log,
    get_recent_user_log,
    get_unmood_evaluated,
    mark_mood_evaluated,
    get_unmemory_evaluated,
    mark_memory_evaluated,
    add_mood_log,
    write_diary_entry,
    read_recent_diary_entries,
    get_history_grouped_by_session,
    get_turns_by_ids,
    get_mood_logs_since,
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
    bump_mention,
    list_active_known_persons,
    list_known_persons_minimal,
    list_relations_all,
    set_emotional_tone,
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
from agent.memory.mindstream.consolidation import (
    generate_daily_diary,
    consolidate_entity_mentions,
    consolidate_person_interest,
    update_profiles,
    update_relations,
)
from agent.memory.mindstream.cleanup import cleanup_history, cleanup_mood_logs, cleanup_heartbeat_runs, run_all_cleanups
from agent.memory.mindstream.mentions import (
    add_mention,
    update_mention_resolution,
    get_recent_mentions,
    get_user_mentions,
    get_pending,
    mark_consolidated,
    update_consolidation_status,
    delete_mention,
    get_consolidated_grouped_by_person,
    get_consolidated_since_grouped_by_person,
    get_resolved_mentions_by_history_ids,
)

# Backward compat alias
get_profile = get_user_information

__all__ = [
    "init_databases",
    "init_core_db",
    "save_turn",
    "get_recent_session_log",
    "get_recent_user_log",
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
    "bump_mention",
    "list_active_known_persons",
    "list_known_persons_minimal",
    "list_relations_all",
    "set_emotional_tone",
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
    "generate_daily_diary",
    "consolidate_entity_mentions",
    "consolidate_person_interest",
    "update_profiles",
    "update_relations",
    "cleanup_history",
    "cleanup_mood_logs",
    "cleanup_heartbeat_runs",
    "run_all_cleanups",
    "add_mention",
    "update_mention_resolution",
    "get_recent_mentions",
    "get_user_mentions",
    "get_pending",
    "mark_consolidated",
    "update_consolidation_status",
    "delete_mention",
    "get_consolidated_grouped_by_person",
    "get_consolidated_since_grouped_by_person",
    "get_resolved_mentions_by_history_ids",
    "add_mood_log",
    "write_diary_entry",
    "read_recent_diary_entries",
    "get_history_grouped_by_session",
    "get_turns_by_ids",
    "get_mood_logs_since",
]
