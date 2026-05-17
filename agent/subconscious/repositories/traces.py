"""
TracesRepository — SQLite database for conversation history.
Database: data/traces.db
Migration: 001_create_traces.sql
Tables: history, session_turns, session_summaries, heartbeat_runs, person_mentions
"""
import sqlite3
from pathlib import Path


class TracesRepository:
    def __init__(self):
        self.db_path = Path(__file__).parent.parent.parent.parent / "data" / "traces.db"
        self.migration_path = Path(__file__).parent.parent / "migrations" / "001_create_traces.sql"

    def get_conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def init(self):
        sql = self.migration_path.read_text(encoding="utf-8")
        conn = self.get_conn()
        conn.executescript(sql)
        conn.commit()
        conn.close()
