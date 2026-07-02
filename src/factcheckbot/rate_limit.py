"""SQLite-backed rolling-window reply rate limiter."""

import time
from collections.abc import Callable

from factcheckbot.seen_store import SeenStore

WINDOW_SECONDS = 60 * 60


class RateLimiter:
    def __init__(
        self,
        store: SeenStore,
        per_user_per_hour: int,
        global_per_hour: int,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._per_user_per_hour = per_user_per_hour
        self._global_per_hour = global_per_hour
        self._now = now
        self._store.connection.execute(
            "CREATE TABLE IF NOT EXISTS replies(author TEXT NOT NULL, ts REAL NOT NULL)"
        )
        self._store.connection.commit()

    def allow(self, author: str) -> tuple[bool, str]:
        cutoff = self._now() - WINDOW_SECONDS
        self._prune(cutoff)

        global_count = self._count("SELECT COUNT(*) FROM replies WHERE ts >= ?", (cutoff,))
        if global_count >= self._global_per_hour:
            return False, "global rate limit"

        user_count = self._count(
            "SELECT COUNT(*) FROM replies WHERE author = ? AND ts >= ?",
            (author, cutoff),
        )
        if user_count >= self._per_user_per_hour:
            return False, "per-user rate limit"
        return True, ""

    def record(self, author: str) -> None:
        self._store.connection.execute(
            "INSERT INTO replies(author, ts) VALUES (?, ?)",
            (author, self._now()),
        )
        self._store.connection.commit()

    def _prune(self, cutoff: float) -> None:
        self._store.connection.execute("DELETE FROM replies WHERE ts < ?", (cutoff,))
        self._store.connection.commit()

    def _count(self, query: str, params: tuple[object, ...]) -> int:
        cursor = self._store.connection.execute(query, params)
        return int(cursor.fetchone()[0])
