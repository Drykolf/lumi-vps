"""
Subconscious gateway — singleton database access for the agent.

Usage:
    from agent.subconscious import traces, core, init_databases

    conn = traces.get_conn()
    conn = core.get_conn()

    init_databases()  # idempotent, safe to call multiple times
"""
from agent.subconscious.repositories.traces import TracesRepository
from agent.subconscious.repositories.core import CoreRepository

traces = TracesRepository()
core = CoreRepository()


def init_databases():
    traces.init()
    core.init()
