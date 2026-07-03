"""Evidence search through ddgs."""

from collections.abc import Callable
from typing import Any

from ddgs import DDGS

from factcheckbot.config import Settings
from factcheckbot.logging_setup import get_logger
from factcheckbot.metrics import Metrics
from factcheckbot.models import Evidence

logger = get_logger(__name__)
FULLTEXT_TOTAL_CHARS = 4000


class EvidenceSearcher:
    def __init__(
        self,
        settings: Settings,
        ddgs_factory: Callable[..., Any] = DDGS,
        extractor_factory: Callable[..., Any] | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self._settings = settings
        self._ddgs_factory = ddgs_factory
        self._extractor_factory = extractor_factory or ddgs_factory
        self._metrics = metrics

    def search(self, query: str) -> list[Evidence]:
        if not query:
            return []
        try:
            ddgs = self._ddgs_factory(timeout=self._settings.search_timeout_seconds)
            raw_results = ddgs.text(
                query,
                region=self._settings.search_region,
                safesearch="moderate",
                timelimit=self._settings.search_timelimit,
                max_results=self._settings.search_max_results,
                backend="auto",
            )
        except Exception as exc:
            if self._metrics is not None:
                self._metrics.search_failures += 1
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

        evidence = [
            Evidence(
                index=index,
                title=str(raw.get("title") or ""),
                url=str(raw.get("href") or ""),
                snippet=_truncate(str(raw.get("body") or ""), self._settings.search_snippet_chars),
            )
            for index, raw in enumerate(deduped, start=1)
        ]
        return self._enrich_fulltext(evidence)

    def _enrich_fulltext(self, evidence: list[Evidence]) -> list[Evidence]:
        if not self._settings.enable_fulltext_evidence or not evidence:
            return evidence
        try:
            extractor = self._extractor_factory(
                timeout=self._settings.evidence_fetch_timeout_seconds
            )
        except Exception:
            return evidence
        if not hasattr(extractor, "extract"):
            return evidence

        enriched = evidence[:]
        remaining_chars = FULLTEXT_TOTAL_CHARS
        for offset, item in enumerate(enriched[: self._settings.evidence_fetch_top_n]):
            if remaining_chars <= 0:
                break
            if not _is_http_url(item.url):
                continue
            try:
                extracted = _extract_fulltext(
                    extractor,
                    item.url,
                    self._settings.evidence_fetch_timeout_seconds,
                )
            except Exception:
                continue
            text = _extracted_text(extracted)
            if not text:
                continue
            char_limit = min(self._settings.evidence_fulltext_chars, remaining_chars)
            snippet = _truncate(text, char_limit)
            enriched[offset] = item.model_copy(update={"snippet": snippet})
            remaining_chars -= len(snippet)
        return enriched


def _truncate(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    if n <= 1:
        return "…"[:n]
    truncated = text[: n - 1].rstrip()
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0].rstrip()
    return f"{truncated}…"


def _extracted_text(extracted: object) -> str:
    if isinstance(extracted, str):
        return extracted
    if isinstance(extracted, dict):
        for key in ("text", "content", "body"):
            value = extracted.get(key)
            if value:
                return str(value)
        return ""
    return ""


def _extract_fulltext(extractor: Any, url: str, timeout: float) -> object:
    # DDGS.extract timeout support depends on the installed version, so this is best effort.
    try:
        return extractor.extract(url, fmt="text_plain", timeout=timeout)
    except TypeError:
        return extractor.extract(url, fmt="text_plain")


def _is_http_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))
