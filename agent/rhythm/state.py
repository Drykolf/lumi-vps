"""
Scheduler execution tracker — wraps heartbeat_state and heartbeat_runs tables.

Stored in core.db (heartbeat_state) and traces.db (heartbeat_runs).
"""
import json
from datetime import datetime, timezone
from agent.subconscious import core, traces

UTC = timezone.utc


# ── Due checks ────────────────────────────────────────────────────────────────

async def rhythm_due(task_name: str, every_minutes: int) -> bool:
    """True if last scheduled run is older than every_minutes (or never run)."""
    conn = core.get_conn()
    row = conn.execute(
        "SELECT last_run_at FROM heartbeat_state WHERE task_name = ?",
        (task_name,),
    ).fetchone()
    conn.close()

    if not row or not row["last_run_at"]:
        return True

    last = datetime.fromisoformat(row["last_run_at"])
    elapsed = (datetime.now(UTC) - last).total_seconds()
    return elapsed > every_minutes * 60


async def rhythm_due_daily(task_name: str, hour: int, minute: int = 0) -> bool:
    """True if task hasn't run today after the given hour:minute COT."""
    from agent.rhythm.cadence import COL
    now = datetime.now(COL)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    conn = core.get_conn()
    row = conn.execute(
        "SELECT last_success_at FROM heartbeat_state WHERE task_name = ?",
        (task_name,),
    ).fetchone()
    conn.close()

    if not row or not row["last_success_at"]:
        return now >= target

    last = datetime.fromisoformat(row["last_success_at"])
    return last < target <= now


async def rhythm_due_weekly(task_name: str, day_of_week: int,
                            hour: int, minute: int = 0) -> bool:
    """True if task hasn't run this week after the given day/hour:minute COT."""
    from agent.rhythm.cadence import COL
    now = datetime.now(COL)
    # Find the most recent occurrence of the target day+time
    days_behind = (now.weekday() - day_of_week) % 7
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    target = target.replace(day=now.day - days_behind)

    conn = core.get_conn()
    row = conn.execute(
        "SELECT last_success_at FROM heartbeat_state WHERE task_name = ?",
        (task_name,),
    ).fetchone()
    conn.close()

    if not row or not row["last_success_at"]:
        return now >= target

    last = datetime.fromisoformat(row["last_success_at"])
    return last < target <= now


# ── Run tracking ─────────────────────────────────────────────────────────────

async def start_rhythm_run(task_name: str) -> int:
    """Insert a heartbeat_runs row and update heartbeat_state. Returns run_id."""
    now = datetime.now(UTC).isoformat()
    conn = traces.get_conn()
    cursor = conn.execute(
        "INSERT INTO heartbeat_runs (task_name, started_at, status) VALUES (?, ?, 'running')",
        (task_name, now),
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()

    conn = core.get_conn()
    conn.execute(
        """UPDATE heartbeat_state
           SET last_run_at = ?, status = 'running', run_count = run_count + 1,
               updated_at = datetime('now')
           WHERE task_name = ?""",
        (now, task_name),
    )
    conn.commit()
    conn.close()

    return run_id


async def mark_rhythm_success(task_name: str, run_id: int,
                              metadata: dict | None = None):
    """Mark a heartbeat_runs row as success and update heartbeat_state."""
    now = datetime.now(UTC).isoformat()
    conn = traces.get_conn()
    conn.execute(
        """UPDATE heartbeat_runs
           SET finished_at = ?, status = 'success', metadata = ?
           WHERE id = ?""",
        (now, json.dumps(metadata) if metadata else None, run_id),
    )
    conn.commit()
    conn.close()

    conn = core.get_conn()
    conn.execute(
        """UPDATE heartbeat_state
           SET last_success_at = ?, status = 'success', last_error = NULL,
               updated_at = datetime('now')
           WHERE task_name = ?""",
        (now, task_name),
    )
    conn.commit()
    conn.close()


async def mark_rhythm_failure(task_name: str, run_id: int, error: Exception):
    """Mark a heartbeat_runs row as failed and update heartbeat_state."""
    now = datetime.now(UTC).isoformat()
    error_str = f"{type(error).__name__}: {error}"

    conn = traces.get_conn()
    conn.execute(
        """UPDATE heartbeat_runs
           SET finished_at = ?, status = 'failed', error = ?
           WHERE id = ?""",
        (now, error_str, run_id),
    )
    conn.commit()
    conn.close()

    conn = core.get_conn()
    conn.execute(
        """UPDATE heartbeat_state
           SET status = 'failed', last_error = ?, updated_at = datetime('now')
           WHERE task_name = ?""",
        (error_str, task_name),
    )
    conn.commit()
    conn.close()


# ── Context manager ──────────────────────────────────────────────────────────

class rhythm_task:
    """Async context manager that tracks job execution in heartbeat_runs/state."""

    def __init__(self, task_name: str):
        self.task_name = task_name
        self._run_id = None

    async def __aenter__(self):
        self._run_id = await start_rhythm_run(self.task_name)
        return self._run_id

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            await mark_rhythm_success(self.task_name, self._run_id)
        else:
            await mark_rhythm_failure(self.task_name, self._run_id, exc_val)
        return False
