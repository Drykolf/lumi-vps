"""
Weekly forgetting: social cooling every Monday 4am COT.
Applies interest decay to inactive non-Jose persons + database cleanup.

The `cleanup_memory_tiers` stub below documents the pending sub-step that
handles deeper memory cleanup (status='forgotten' transitions, Mem0 downgrade,
grace-period deletion). It belongs to the weekly cycle — NOT the nightly
quiescence — because it operates on long-horizon thresholds that don't
benefit from nightly evaluation.
"""
from agent.rhythm.state import rhythm_task
from agent.substrate.logger import get_logger

logger = get_logger("rhythm.forgetting")


async def weekly_decay() -> None:
    """Weekly interest decay and database cleanup."""
    async with rhythm_task("weekly_decay"):
        await weekly_interest_decay()
        async with rhythm_task("weekly_cleanup"):
            await cleanup_old_logs()


async def weekly_interest_decay() -> None:
    """Apply 28-day interest decay to inactive non-Jose persons."""
    from agent.memory import run_decay
    run_decay()
    logger.info("weekly interest decay applied")


async def cleanup_old_logs() -> None:
    """Purge old entries from history, mood_logs, and heartbeat runs tables."""
    from agent.memory.mindstream.cleanup import run_all_cleanups
    results = run_all_cleanups()
    logger.info(
        f"weekly cleanup | history={results['history']} "
        f"mood_logs={results['mood_logs']} "
        f"heartbeat_runs={results['heartbeat_runs']}"
    )


async def cleanup_memory_tiers() -> dict | None:
    """TODO (weekly cycle, not yet wired): tier-aware cleanup of long-horizon
    memory state.

    Responsibilities when implemented:
      1. Mark persons crossing the `forgotten` threshold:
           interest_score <= 0.05 AND status='decaying'
           AND last_mentioned <= now - 30d
         → set `status='forgotten'` + `forgotten_at=now`.
      2. Delete persons in `status='forgotten'` whose grace period has elapsed
         (`forgotten_at <= now - 30d`). CASCADE clears `relations` and
         `person_identifiers` automatically.
      3. Hard-delete their Mem0 entries via search-then-delete on
         `metadata.person_id`.

    Recovery via heartbeat_state bookmark (`weekly.cleanup_memory_tiers`): all
    queries are threshold-based so re-running is idempotent.

    Expected metrics:
      marked_forgotten, deleted_forgotten, mem0_memories_deleted, skipped_errors

    Not invoked from `weekly_decay()` yet — moved here from nightly_quiescence
    pending a deliberate implementation session for the Mem0 client work
    (delete_memory wrapper, search_person_memory_ids, metadata.person_id
    pipeline). See plan: phase4_plan.md.
    """
    return None
