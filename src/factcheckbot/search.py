"""Evidence search through ddgs."""

from collections.abc import Callable
from typing import Any

from ddgs import DDGS

from factcheckbot.config import Settings
from factcheckbot.logging_setup import get_logger
from factcheckbot.models import Evidence

logger = get_logger(__name__)


class EvidenceSearcher:
    def __init__(self, settings: Settings, ddgs_factory: Callable[..., Any] = DDGS) -> None:
        self._settings = settings
        self._ddgs_factory = ddgs_factory

    def search(self, query: str) -> list[Evidence]:
        if not query:
            return []
        try:
            raw_results = self._ddgs_factory(timeout=self._settings.search_timeout_seconds).text(
                query,
                region=self._settings.search_region,
                safesearch="moderate",
                timelimit=self._settings.search_timelimit,
                max_results=self._settings.search_max_results,
                backend="auto",
            )
        except Exception as exc:
            logger.warning("Search failed: %s", exc)
            return []

        deduped: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for raw in raw_results or []:
            url = str(raw.get("href") or "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(raw)

        return [
            Evidence(
                index=index,
                title=str(raw.get("title") or ""),
                url=str(raw.get("href") or ""),
                snippet=_truncate(str(raw.get("body") or ""), self._settings.search_snippet_chars),
            )
            for index, raw in enumerate(deduped, start=1)
        ]


def _truncate(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    if n <= 1:
        return "…"[:n]
    truncated = text[: n - 1].rstrip()
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0].rstrip()
    return f"{truncated}…"
