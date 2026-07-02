"""SQLite-backed store for processed Reddit item ids."""

import sqlite3
import time
from pathlib import Path


class SeenStore:
    def __init__(self, path: str) -> None:
        self._path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def _init_schema(self) -> None:
        self._connection.execute("CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY, ts REAL)")
        self._connection.commit()

    def is_seen(self, item_id: str) -> bool:
        cursor = self._connection.execute("SELECT 1 FROM seen WHERE id = ?", (item_id,))
        return cursor.fetchone() is not None

    def mark_seen(self, item_id: str) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO seen(id, ts) VALUES (?, ?)",
            (item_id, time.time()),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()
