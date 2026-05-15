"""
Database cleanup — periodic pruning of old rows from traces.db.
"""
from datetime import datetime, timezone, timedelta
from agent.subconscious import traces
from agent.substrate.logger import get_logger

logger = get_logger("memory.cleanup")
UTC = timezone.utc


def _cutoff(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def cleanup_history(days: int = 15) -> int:
    cutoff = _cutoff(days)
    conn = traces.get_conn()
    cursor = conn.execute("DELETE FROM history WHERE ts < ?", (cutoff,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"history cleanup | deleted={deleted} | cutoff_before_{days}d")
    return deleted


def cleanup_summaries(days: int = 30) -> int:
    cutoff = _cutoff(days)
    conn = traces.get_conn()
    cursor = conn.execute("DELETE FROM session_summaries WHERE created_at < ?", (cutoff,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"session_summaries cleanup | deleted={deleted} | cutoff_before_{days}d")
    return deleted


def cleanup_heartbeat_runs(days: int = 7) -> int:
    cutoff = _cutoff(days)
    conn = traces.get_conn()
    cursor = conn.execute("DELETE FROM heartbeat_runs WHERE started_at < ?", (cutoff,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"heartbeat_runs cleanup | deleted={deleted} | cutoff_before_{days}d")
    return deleted


def run_all_cleanups() -> dict[str, int]:
    return {
        "history": cleanup_history(),
        "session_summaries": cleanup_summaries(),
        "heartbeat_runs": cleanup_heartbeat_runs(),
    }
