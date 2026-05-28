"""
Nightly quiescence: deep maintenance at 3am COT.

Execution order (each step depends on the previous one having a stable view):
  1. consolidate_entity_mentions   — resolve pending mentions, create new
                                      persons, delete anonymous ones
  2. consolidate_person_interest   — LLM-evaluated per-person deltas
  3. update_profiles               — aliases / name / emotional_tone refinement (identity-only)
  4. update_relations              — new relations + infer_family_relations
  5. consolidate_daily_memories    — extract atomic facts → Mem0 (subject-centric Modelo C)
  6. extract_daily_learnings       — diary entries (already wired)
  7. analyze_daily_tasks           — skill_proposals (stub)

Memory tier cleanup (decay/downgrade/forgotten) lives in the weekly cycle
(see agent/rhythm/routines/forgetting.py:cleanup_memory_tiers).

Each step is invoked through `_run_step`, which wraps the coroutine in its own
`rhythm_task("quiescence.<name>")` context. heartbeat_state.last_success_at for
that task acts as the canonical bookmark: when a step fails, its bookmark stays
frozen and tomorrow's run picks up where the last success left off (self-healing
recovery without needing per-mention flags).
"""
from datetime import datetime, timezone, timedelta
from typing import Awaitable, Callable

from agent.rhythm.state import rhythm_task, get_last_success
from agent.substrate.logger import get_logger
from agent.substrate.nightly_log import NightlyLog

logger = get_logger("rhythm.quiescence")
UTC = timezone.utc


async def _run_step(
    log: NightlyLog,
    name: str,
    coro_factory: Callable[[], Awaitable[dict | None]],
    expected_keys: list[str] | None = None,
) -> dict | None:
    """Run one sub-step inside its own `rhythm_task("quiescence.<name>")`,
    isolating failures and normalising logging.

    Contract for every nightly sub-function: return a `dict` of metrics or
    `None`. On success, rhythm_task automatically stamps last_success_at,
    which downstream runs read as period_start. On failure the bookmark stays
    frozen and the next nightly's window stretches back to recover.
    """
    sub_task = f"quiescence.{name}"
    try:
        async with rhythm_task(sub_task):
            result = await coro_factory()
    except Exception as e:
        logger.exception(f"[quiescence] {name} failed")
        log.error(name, e)
        return None

    if result is None:
        log.section(name, status="ok")
        return None

    if expected_keys:
        for key in expected_keys:
            if key not in result:
                logger.warning(
                    f"[quiescence] {name} missing expected metric '{key}'"
                )
                result[key] = None

    log.section(name, **result)
    return result


async def nightly_quiescence() -> None:
    """Deep nightly maintenance at 3am COT."""
    log = NightlyLog("nightly_quiescence")
    async with rhythm_task("nightly_quiescence"):
        try:
            # ── Step 1 — entity mentions ──────────────────────────────────
            # Self-healing via consolidation_status='pending' on person_mentions.
            await _run_step(
                log,
                "consolidate_entity_mentions",
                consolidate_entity_mentions,
                expected_keys=[
                    "total_pending",
                    "resolved_existing",
                    "created_new",
                    "deleted",
                    "needs_review",
                    "affected_person_ids",
                ],
            )

            # ── Step 2 — interest deltas ──────────────────────────────────
            await _run_step(
                log,
                "consolidate_person_interest",
                consolidate_person_interest,
                expected_keys=[
                    "persons_evaluated",
                    "deltas_applied",
                    "tone_updates",
                    "skipped",
                ],
            )

            # ── Step 3 — profiles ─────────────────────────────────────────
            await _run_step(
                log,
                "update_profiles",
                update_profiles,
                expected_keys=[
                    "persons_evaluated",
                    "aliases_added",
                    "names_corrected",
                    "tones_updated",
                    "skipped",
                ],
            )

            # ── Step 4 — relations ────────────────────────────────────────
            await _run_step(
                log,
                "update_relations",
                update_relations,
                expected_keys=[
                    "persons_evaluated",
                    "relations_added",
                    "relations_inferred",
                    "skipped",
                ],
            )

            # ── Step 5 — daily memories ───────────────────────────────────
            await _run_step(
                log,
                "consolidate_daily_memories",
                consolidate_daily_memories,
                expected_keys=[
                    "candidates",
                    "persons_evaluated",
                    "persons_skipped_threshold",
                    "persons_skipped_unknown",
                    "facts_extracted",
                    "mem0_calls",
                    "mem0_results",
                ],
            )

            # ── Step 6 — diary ────────────────────────────────────────────
            await _run_step(
                log,
                "extract_daily_learnings",
                extract_daily_learnings,
                expected_keys=["entries_written", "period_start", "period_end"],
            )

            # ── Step 7 — skill pattern detection ──────────────────────────
            await _run_step(
                log,
                "analyze_daily_tasks",
                analyze_daily_tasks,
                expected_keys=[
                    "skipped",
                    "skipped_reason",
                    "read_only",
                    "turns_analyzed",
                    "categories_found",
                    "patterns_crossing_threshold",
                    "proposals_inserted",
                    "proposals_skipped_duplicate",
                ],
            )
        finally:
            log.note("--- run complete ---")


# ── Step 1 ─────────────────────────────────────────────────────────────────────

async def consolidate_entity_mentions() -> dict:
    """Resolve all pending person_mentions via LLM. See
    agent/memory/mindstream/consolidation.py for the implementation.

    Self-healing pattern: this step queries by status, not time window, so any
    mention left as 'pending' from a prior failed run is picked up automatically.
    """
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

async def consolidate_person_interest() -> dict:
    """LLM-evaluated per-person interest deltas. Skips Jose.

    Reads its own last_success_at bookmark to compute period_start, so a
    missed night's worth of consolidated mentions is caught up automatically.
    """
    from agent.memory.mindstream.consolidation import (
        consolidate_person_interest as _impl,
    )
    period_start = await get_last_success("quiescence.consolidate_person_interest")
    metrics = await _impl(period_start)
    logger.info(
        f"[quiescence] interest_consolidation done: "
        f"evaluated={metrics['persons_evaluated']} "
        f"deltas={metrics['deltas_applied']} "
        f"tones={metrics['tone_updates']}"
    )
    return metrics


# ── Step 3 ─────────────────────────────────────────────────────────────────────

async def update_profiles() -> dict:
    """Identity refinement for persons mentioned in the window: aliases, name
    corrections, emotional_tone. Reads its own last_success_at bookmark to
    compute period_start; a failed prior run extends tonight's window."""
    from agent.memory.mindstream.consolidation import update_profiles as _impl
    period_start = await get_last_success("quiescence.update_profiles")
    metrics = await _impl(period_start)
    logger.info(
        f"[quiescence] profiles done: evaluated={metrics['persons_evaluated']} "
        f"aliases={metrics['aliases_added']} names={metrics['names_corrected']} "
        f"tones={metrics['tones_updated']}"
    )
    return metrics


# ── Step 4 ─────────────────────────────────────────────────────────────────────

async def update_relations() -> dict:
    """Detect new relations between known persons + run rule-based family
    inference. Reads its own last_success_at bookmark for period_start."""
    from agent.memory.mindstream.consolidation import update_relations as _impl
    period_start = await get_last_success("quiescence.update_relations")
    metrics = await _impl(period_start)
    logger.info(
        f"[quiescence] relations done: evaluated={metrics['persons_evaluated']} "
        f"added={metrics['relations_added']} inferred={metrics['relations_inferred']}"
    )
    return metrics


# ── Step 5 ─────────────────────────────────────────────────────────────────────

async def consolidate_daily_memories() -> dict:
    """Per-person LLM extraction of atomic facts → Mem0 (subject-centric Modelo C).

    Implementation in agent/memory/mindstream/consolidation.py. Reads its own
    last_success_at bookmark to compute period_start; a failed prior run
    extends tonight's window automatically.
    """
    from agent.memory.mindstream.consolidation import (
        consolidate_daily_memories as _impl,
    )
    period_start = await get_last_success("quiescence.consolidate_daily_memories")
    metrics = await _impl(period_start)
    logger.info(
        f"[quiescence] daily_memories done: "
        f"candidates={metrics['candidates']} "
        f"evaluated={metrics['persons_evaluated']} "
        f"facts={metrics['facts_extracted']} "
        f"mem0_calls={metrics['mem0_calls']} "
        f"mem0_results={metrics['mem0_results']}"
    )
    return metrics


# ── Step 6 ─────────────────────────────────────────────────────────────────────

async def extract_daily_learnings() -> dict:
    """Generate diary entries for the period since the last diary run.

    Self-healing via `MAX(period_end) FROM diary` — independent of
    heartbeat_state bookmark (the diary table itself is the authoritative log).
    """
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
    return {
        "entries_written": written,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }


# ── Step 7 ─────────────────────────────────────────────────────────────────────

async def analyze_daily_tasks() -> dict | None:
    """Detect recurring user-request patterns and stage them in `skill_proposals`.

    Despite the historic name (this used to be planned as a task-log feature),
    the actual implementation focuses on skill-evolution: cluster user turns
    from the last 14 days into request categories, apply detection thresholds,
    write draft .md files under `agent/identity/skills/_drafts/`, and insert
    a `skill_proposals` row per draft for Jose's manual review.

    See .architecture/policies/skill_evolution.md (canonical spec) and
    agent/memory/mindstream/skills.py for the implementation.

    period_start is read from this step's bookmark for consistency with other
    nightly subs, but the actual data window is fixed at 14 days inside the
    detector — the bookmark is informational only.
    """
    from agent.memory.mindstream.skills import detect_skill_patterns
    period_start = await get_last_success("quiescence.analyze_daily_tasks")
    metrics = await detect_skill_patterns(period_start)
    logger.info(
        f"[quiescence] skill_patterns done: "
        f"turns={metrics['turns_analyzed']} "
        f"categories={metrics['categories_found']} "
        f"crossing={metrics['patterns_crossing_threshold']} "
        f"inserted={metrics['proposals_inserted']} "
        f"duplicates={metrics['proposals_skipped_duplicate']} "
        f"read_only={metrics['read_only']} "
        f"skipped={metrics['skipped']}"
    )
    return metrics


# ── Removed / migrated ────────────────────────────────────────────────────────

async def update_user_profiles() -> None:
    """No-op: user_profiles table removed. Migrated to known_persons + Mem0."""
    pass


async def update_relationship_memory() -> None:
    """Deprecated: split into update_profiles + update_relations. Kept as
    no-op shim so any external caller fails soft. Will be removed once no
    callers remain."""
    pass
