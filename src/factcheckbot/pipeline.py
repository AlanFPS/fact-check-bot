"""Fact-check pipeline orchestration."""

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass

from factcheckbot.config import Settings
from factcheckbot.google_factcheck import GoogleFactCheckClient
from factcheckbot.llm import LlmClient
from factcheckbot.metrics import Metrics
from factcheckbot.models import PipelineOutcome, TriggerContext
from factcheckbot.search import EvidenceSearcher
from factcheckbot.seen_store import SeenStore
from factcheckbot.triggers import normalize_claim


@dataclass
class Pipeline:
    settings: Settings
    searcher: EvidenceSearcher
    llm: LlmClient
    google: GoogleFactCheckClient | None = None
    cache_store: SeenStore | None = None
    metrics: Metrics | None = None
    now: Callable[[], float] = time.time

    def resolve_claim(
        self,
        ctx: TriggerContext,
        parent_text_getter: Callable[[], str | None],
    ) -> str:
        inline = normalize_claim(ctx.inline_query, self.settings.max_claim_chars)
        if inline:
            return inline
        parent_text = parent_text_getter()
        if not parent_text:
            return ""
        extracted = self.llm.extract_claim(parent_text)
        return normalize_claim(extracted, self.settings.max_claim_chars)

    def run(self, claim: str) -> PipelineOutcome:
        cache_key = _cache_key(
            normalize_claim(claim, self.settings.max_claim_chars),
            _tier_scope(self.settings, self.google),
        )
        if self.settings.enable_verdict_cache and self.cache_store is not None:
            payload = self.cache_store.get_cached_verdict(
                cache_key,
                self.settings.cache_ttl_seconds,
                self.now(),
            )
            if payload is not None:
                try:
                    outcome = PipelineOutcome.model_validate_json(payload)
                    self._record_outcome(outcome)
                    return outcome
                except Exception:
                    pass

        outcome = self._run_uncached(claim)
        if self.settings.enable_verdict_cache and self.cache_store is not None:
            now = self.now()
            self.cache_store.prune_verdict_cache(now - self.settings.cache_ttl_seconds)
            self.cache_store.store_cached_verdict(
                cache_key,
                outcome.source,
                outcome.model_dump_json(),
                now,
            )
        self._record_outcome(outcome)
        return outcome

    def _run_uncached(self, claim: str) -> PipelineOutcome:
        if self.google is not None and self.google.enabled:
            google_claims = self.google.search(claim)
            if google_claims:
                return PipelineOutcome(
                    source="google",
                    claim=claim,
                    google_claims=google_claims,
                )

        evidence = self.searcher.search(claim)
        result = self.llm.fact_check(claim, evidence)
        return PipelineOutcome(
            source="llm",
            claim=claim,
            llm_result=result,
            evidence=evidence,
        )

    def _record_outcome(self, outcome: PipelineOutcome) -> None:
        if self.metrics is None:
            return
        if outcome.source == "google":
            self.metrics.google_hits += 1
        elif outcome.llm_result is not None:
            self.metrics.llm_verdicts += 1
            self.metrics.record_verdict(outcome.llm_result.verdict.value)


def _cache_key(normalized_claim: str, tier_scope: str) -> str:
    return hashlib.sha256(f"{normalized_claim}|{tier_scope}".encode()).hexdigest()


def _tier_scope(settings: Settings, google: GoogleFactCheckClient | None) -> str:
    if google is not None and google.enabled:
        scope = (
            f"google-first:{settings.google_factcheck_language}:"
            f"{settings.google_factcheck_max_claims}"
        )
    else:
        scope = "llm-only"
    if settings.enable_fulltext_evidence:
        scope = f"{scope}:ft"
    return scope
