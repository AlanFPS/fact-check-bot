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
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS pending(item_id TEXT PRIMARY KEY, ts REAL)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS verdict_cache("
            "key TEXT PRIMARY KEY, source TEXT, payload TEXT, ts REAL)"
        )
        self._connection.commit()

    def is_seen(self, item_id: str) -> bool:
        cursor = self._connection.execute("SELECT 1 FROM seen WHERE id = ?", (item_id,))
        return cursor.fetchone() is not None

    def is_pending(self, item_id: str) -> bool:
        cursor = self._connection.execute("SELECT 1 FROM pending WHERE item_id = ?", (item_id,))
        return cursor.fetchone() is not None

    def mark_seen(self, item_id: str) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO seen(id, ts) VALUES (?, ?)",
            (item_id, time.time()),
        )
        self._connection.commit()

    def mark_pending(self, item_id: str) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO pending(item_id, ts) VALUES (?, ?)",
            (item_id, time.time()),
        )
        self._connection.commit()

    def clear_pending(self, item_id: str) -> None:
        self._connection.execute("DELETE FROM pending WHERE item_id = ?", (item_id,))
        self._connection.commit()

    def list_pending(self) -> list[str]:
        cursor = self._connection.execute("SELECT item_id FROM pending ORDER BY ts ASC")
        return [str(row[0]) for row in cursor.fetchall()]

    def mark_seen_and_clear_pending(self, item_id: str) -> None:
        now = time.time()
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO seen(id, ts) VALUES (?, ?)",
                (item_id, now),
            )
            self._connection.execute("DELETE FROM pending WHERE item_id = ?", (item_id,))

    def get_cached_verdict(self, key: str, ttl_seconds: int, now: float) -> str | None:
        cutoff = now - ttl_seconds
        with self._connection:
            self._connection.execute("DELETE FROM verdict_cache WHERE ts < ?", (cutoff,))
        cursor = self._connection.execute(
            "SELECT payload FROM verdict_cache WHERE key = ? AND ts >= ?",
            (key, cutoff),
        )
        row = cursor.fetchone()
        return str(row[0]) if row else None

    def store_cached_verdict(self, key: str, source: str, payload: str, now: float) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO verdict_cache(key, source, payload, ts) VALUES (?, ?, ?, ?)",
            (key, source, payload, now),
        )
        self._connection.commit()

    def prune_verdict_cache(self, cutoff: float) -> None:
        self._connection.execute("DELETE FROM verdict_cache WHERE ts < ?", (cutoff,))
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()
