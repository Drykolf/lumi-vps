"""
Weekly forgetting: social cooling every Monday 4am COT.
Applies interest decay to inactive non-Jose persons.
"""
from agent.rhythm.state import rhythm_task


async def weekly_forgetting() -> None:
    """Weekly interest decay for inactive persons."""
    async with rhythm_task("weekly_forgetting"):
        await weekly_interest_decay()


async def weekly_interest_decay() -> None:
    ...


async def decay_inactive_people() -> None:
    ...


async def forget_stale_people() -> None:
    ...
