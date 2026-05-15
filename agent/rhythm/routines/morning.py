"""
Morning rhythm: Lumi wakes more centered at 7am COT.
Applies mood regression toward baseline per mood_policy.md §329-352.
"""
from agent.rhythm.state import rhythm_task


async def daily_morning() -> None:
    """Daily morning regression toward baseline at 7am COT."""
    async with rhythm_task("daily_morning"):
        await morning_regression()


async def morning_regression() -> None:
    """Pulls mood fields partially toward baseline."""
    from agent.affect import morning_reset
    from agent.substrate.logger import get_logger
    logger = get_logger("rhythm.morning")

    new_state = morning_reset()
    logger.info(
        f"morning regression | valence={new_state['mood_valence']:.2f} "
        f"energy={new_state['mood_energy']:.2f} "
        f"irritation={new_state['irritation']:.2f}"
    )
