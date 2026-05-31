"""
Public API for memory — all agent modules import from here.

Underlying implementations:
  agent/memory/episodic.py       — historial, canales, resumenes (traces.db)
  agent/memory/semantic.py       — Mem0 semantico
  agent/memory/mindstream/social.py         — personas, relaciones, lumi_state (core.db)
  agent/memory/mindstream/consolidation.py  — generacion LLM de resumenes por canal (traces.db)

Usage:
    from agent.memory import get_recent_user_log, save_turn, add_memory, ...
"""
from agent.subconscious import init_databases
from agent.memory.episodic import (
    save_turn,
    get_recent_channel_log,
    get_recent_user_log,
    get_history_since,
    add_mood_log,
    write_diary_entry,
    read_recent_diary_entries,
    get_history_grouped_by_channel,
    get_turns_by_ids,
    get_mood_logs_since,
    get_active_user_ids_in_period,
    get_turns_in_period_by_user,
    get_channel_context_for_user_in_period,
)
from agent.memory.semantic import (
    search_relevant,
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
    consolidate_daily_memories,
)
from agent.memory.mindstream.skills import detect_skill_patterns
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
    "get_recent_channel_log",
    "get_recent_user_log",
    "get_history_since",
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
    "consolidate_daily_memories",
    "detect_skill_patterns",
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
    "get_history_grouped_by_channel",
    "get_turns_by_ids",
    "get_mood_logs_since",
    "get_active_user_ids_in_period",
    "get_turns_in_period_by_user",
    "get_channel_context_for_user_in_period",
]
