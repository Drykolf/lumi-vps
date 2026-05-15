"""
Weekly forgetting: social cooling every Monday 4am COT.
Applies interest decay to inactive non-Jose persons + database cleanup.
"""
from agent.rhythm.state import rhythm_task
from agent.substrate.logger import get_logger

logger = get_logger("rhythm.forgetting")


async def weekly_forgetting() -> None:
    """Weekly interest decay and database cleanup."""
    async with rhythm_task("weekly_forgetting"):
        await weekly_interest_decay()
        async with rhythm_task("weekly_cleanup"):
            await cleanup_old_logs()


async def weekly_interest_decay() -> None:
    ...


async def cleanup_old_logs() -> None:
    """Purge old entries from history, summaries, and heartbeat runs tables."""
    from agent.memory.mindstream.cleanup import run_all_cleanups
    results = run_all_cleanups()
    logger.info(
        f"weekly cleanup | history={results['history']} "
        f"summaries={results['session_summaries']} "
        f"heartbeat_runs={results['heartbeat_runs']}"
    )


async def decay_inactive_people() -> None:
    ...


async def forget_stale_people() -> None:
    ...
