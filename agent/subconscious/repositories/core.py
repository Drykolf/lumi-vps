"""
CoreRepository — SQLite database for Lumi's internal state and social graph.
Database: data/core.db
Migration: 002_create_core.sql
Seeds: seeds/initial_state.sql
Tables: known_persons, relations, lumi_state, skill_proposals
"""
import sqlite3
from pathlib import Path


class CoreRepository:
    def __init__(self):
        self.db_path = Path(__file__).parent.parent.parent.parent / "data" / "core.db"
        self.migration_path = Path(__file__).parent.parent / "migrations" / "002_create_core.sql"
        self.seeds_path = Path(__file__).parent.parent / "seeds" / "initial_state.sql"

    def get_conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.execute("PRAGMA journal_mode = WAL")
        # Match connect(timeout=30): this PRAGMA otherwise overrode it down to
        # 5s, giving writers far less slack under contention.
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def init(self):
        migration = self.migration_path.read_text(encoding="utf-8")
        conn = self.get_conn()
        conn.executescript(migration)
        conn.commit()
        conn.close()

        seeds = self.seeds_path.read_text(encoding="utf-8")
        conn = self.get_conn()
        conn.executescript(seeds)
        conn.commit()
        conn.close()
