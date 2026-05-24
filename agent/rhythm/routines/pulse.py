"""
Frequent rhythm tick — every 15 minutes.
Handles idle sessions and catch-up tasks.
"""
from agent.rhythm.state import rhythm_task
from agent.substrate.logger import get_logger
logger = get_logger("rhythm.pulse")


async def rhythm_tick():
    """Every 15 min: idle session cleanup and catch-up."""
    async with rhythm_task("rhythm_tick"):
        await process_pending_mood_evaluations()
        await catch_up_pending_work()


async def process_pending_mood_evaluations() -> None:
    """Placeholder: apply session mood deltas for unevaluated sessions."""
    ...


async def catch_up_pending_work() -> None:
    """Placeholder: retry failed or incomplete runs from heartbeat_runs."""
    ...
