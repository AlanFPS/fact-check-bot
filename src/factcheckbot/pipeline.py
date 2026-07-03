"""Fact-check pipeline orchestration."""

from collections.abc import Callable
from dataclasses import dataclass

from factcheckbot.config import Settings
from factcheckbot.google_factcheck import GoogleFactCheckClient
from factcheckbot.llm import LlmClient
from factcheckbot.models import PipelineOutcome, TriggerContext
from factcheckbot.search import EvidenceSearcher
from factcheckbot.triggers import normalize_claim


@dataclass
class Pipeline:
    settings: Settings
    searcher: EvidenceSearcher
    llm: LlmClient
    google: GoogleFactCheckClient | None = None

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
