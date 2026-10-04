"""SQLite of the gateway in the stand state folder. Tables arrive in tasks 04-07."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

# Each task appends its own CREATE TABLE IF NOT EXISTS statements here.
SCHEMA = """
"""


class GatewayStore:
    def __init__(self, db_path: Path):
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self.db.close()
