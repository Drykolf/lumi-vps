"""
Nightly quiescence: deep maintenance at 3am COT.

Execution order (each step depends on the previous one having a stable view):
  1. consolidate_entity_mentions   — resolve pending mentions, create new
                                      persons, delete anonymous ones
  2. consolidate_person_interest   — LLM-evaluated per-person deltas
  3. update_profiles               — notes / aliases / emotional_tone refinement
  4. update_relations              — new relations + infer_family_relations
  5. consolidate_daily_memories    — extract atomic facts → Mem0
  6. extract_daily_learnings       — diary entries (already wired)
  7. cleanup_memory_tiers          — decay + downgrade + forgotten cleanup
  8. analyze_daily_tasks           — skill_proposals
"""
from datetime import datetime, timezone, timedelta
from agent.rhythm.state import rhythm_task
from agent.substrate.logger import get_logger
from agent.substrate.nightly_log import NightlyLog

logger = get_logger("rhythm.quiescence")
UTC = timezone.utc


async def nightly_quiescence() -> None:
    """Deep nightly maintenance at 3am COT."""
    log = NightlyLog("nightly_quiescence")
    async with rhythm_task("nightly_quiescence"):
        affected: set[str] = set()

        try:
            entity_metrics = await consolidate_entity_mentions()
            log.section(
                "consolidate_entity_mentions",
                total_pending=entity_metrics["total_pending"],
                resolved_existing=entity_metrics["resolved_existing"],
                created_new=entity_metrics["created_new"],
                deleted=entity_metrics["deleted"],
                needs_review=entity_metrics["needs_review"],
                affected_person_ids=entity_metrics["affected_person_ids"],
            )
            affected = entity_metrics.get("affected_person_ids", set())
        except Exception as e:
            logger.exception("[quiescence] consolidate_entity_mentions failed")
            log.error("consolidate_entity_mentions", e)

        try:
            interest_metrics = await consolidate_person_interest(affected)
            log.section(
                "consolidate_person_interest",
                persons_evaluated=interest_metrics["persons_evaluated"],
                deltas_applied=interest_metrics["deltas_applied"],
                tone_updates=interest_metrics["tone_updates"],
                skipped=interest_metrics.get("skipped", 0),
            )
        except Exception as e:
            logger.exception("[quiescence] consolidate_person_interest failed")
            log.error("consolidate_person_interest", e)

        await update_profiles(affected)
        await update_relations(affected)
        await consolidate_daily_memories()
        await extract_daily_learnings()
        await cleanup_memory_tiers()
        await analyze_daily_tasks()

        log.note("--- run complete ---")


# ── Step 1 ─────────────────────────────────────────────────────────────────────

async def consolidate_entity_mentions() -> dict:
    """Resolve all pending person_mentions via LLM. See
    agent/memory/mindstream/consolidation.py for the implementation."""
    from agent.memory.mindstream.consolidation import (
        consolidate_entity_mentions as _impl,
    )
    metrics = await _impl()
    logger.info(
        f"[quiescence] entity_consolidation done: "
        f"resolved={metrics['resolved_existing']} "
        f"created={metrics['created_new']} "
        f"deleted={metrics['deleted']} "
        f"needs_review={metrics['needs_review']} "
        f"affected={len(metrics['affected_person_ids'])}"
    )
    return metrics


# ── Step 2 ─────────────────────────────────────────────────────────────────────

async def consolidate_person_interest(affected_person_ids: set[str]) -> dict:
    """LLM-evaluated per-person interest deltas. Skips Jose."""
    from agent.memory.mindstream.consolidation import (
        consolidate_person_interest as _impl,
    )
    metrics = await _impl(affected_person_ids)
    logger.info(
        f"[quiescence] interest_consolidation done: "
        f"evaluated={metrics['persons_evaluated']} "
        f"deltas={metrics['deltas_applied']} "
        f"tones={metrics['tone_updates']}"
    )
    return metrics


# ── Step 3 ─────────────────────────────────────────────────────────────────────

async def update_profiles(affected_person_ids: set[str]) -> None:
    """B5 pending — extract new facts about persons (notes, aliases,
    emotional_tone refinements) from today's turns and update known_persons.

    Operates only on the persons whose mentions were touched tonight."""
    ...


# ── Step 4 ─────────────────────────────────────────────────────────────────────

async def update_relations(affected_person_ids: set[str]) -> None:
    """B5 pending — detect new relation patterns from today's turns and apply
    `infer_family_relations()`. Operates only on affected persons (and their
    neighbours in the relation graph)."""
    ...


# ── Step 5 ─────────────────────────────────────────────────────────────────────

async def consolidate_daily_memories() -> None:
    """B5 pending — extract atomic facts per person from today's turns and push
    to Mem0 via `add_memory()` with metadata.person_id."""
    ...


# ── Step 6 ─────────────────────────────────────────────────────────────────────

async def extract_daily_learnings() -> None:
    """Generate diary entries for the period since the last diary run."""
    from agent.memory.mindstream.consolidation import generate_daily_diary
    from agent.subconscious import traces

    period_end = datetime.now(UTC)

    conn = traces.get_conn()
    row = conn.execute(
        "SELECT MAX(period_end) FROM diary"
    ).fetchone()
    conn.close()

    if row and row[0]:
        period_start = datetime.fromisoformat(row[0])
    else:
        period_start = period_end - timedelta(hours=24)

    written = await generate_daily_diary(period_start, period_end)
    logger.info(f"[diary] nightly run | period_start={period_start.isoformat()} "
                f"period_end={period_end.isoformat()} | entries={written}")


# ── Step 7 ─────────────────────────────────────────────────────────────────────

async def cleanup_memory_tiers() -> None:
    """B5 pending — apply decay (`run_decay()`), downgrade Mem0 storage for
    persons whose interest_score crossed thresholds, and delete persons in
    `status='forgotten'` after a grace period."""
    ...


# ── Step 8 ─────────────────────────────────────────────────────────────────────

async def analyze_daily_tasks() -> None:
    """B5 pending — detect pending tasks mentioned in turns and stage them in
    the `skill_proposals` table."""
    ...


# ── Removed / migrated ────────────────────────────────────────────────────────

async def update_user_profiles() -> None:
    """No-op: user_profiles table removed. Migrated to known_persons + Mem0."""
    pass


async def update_relationship_memory() -> None:
    """Deprecated: split into update_profiles + update_relations. Kept as
    no-op shim so any external caller fails soft. Will be removed once no
    callers remain."""
    pass
