"""Pydantic models for fact-checking data."""

import math
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_REASONING_CHARS = 1500


class Verdict(StrEnum):
    TRUE = "TRUE"
    MOSTLY_TRUE = "MOSTLY TRUE"
    MIXED = "MIXED"
    MOSTLY_FALSE = "MOSTLY FALSE"
    FALSE = "FALSE"
    UNVERIFIABLE = "UNVERIFIABLE"


class Evidence(BaseModel):
    index: int
    title: str
    url: str
    snippet: str


class GoogleReview(BaseModel):
    publisher: str
    textual_rating: str
    url: str
    title: str | None = None
    review_date: str | None = None


class GoogleClaim(BaseModel):
    text: str
    claimant: str | None = None
    reviews: list[GoogleReview]


class FactCheckResult(BaseModel):
    verdict: Verdict
    confidence: float
    reasoning: str
    cited_sources: list[int]

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return min(max(value, 0.0), 1.0)

    @field_validator("reasoning")
    @classmethod
    def truncate_reasoning(cls, value: str) -> str:
        if len(value) <= MAX_REASONING_CHARS:
            return value
        return value[: MAX_REASONING_CHARS - 1].rstrip() + "…"

    @field_validator("cited_sources")
    @classmethod
    def sanitize_cited_sources(cls, values: list[int]) -> list[int]:
        seen: set[int] = set()
        sanitized: list[int] = []
        for value in values:
            if value < 1 or value in seen:
                continue
            seen.add(value)
            sanitized.append(value)
        return sanitized


class TriggerContext(BaseModel):
    item_id: str
    author: str | None
    inline_query: str
    permalink: str
    source: Literal["comment_stream", "inbox_mention"]


class PipelineOutcome(BaseModel):
    """Tagged result of Pipeline.run so the bot knows which renderer to use."""

    source: Literal["google", "llm"]
    claim: str
    google_claims: list[GoogleClaim] = Field(default_factory=list)
    llm_result: FactCheckResult | None = None
    evidence: list[Evidence] = Field(default_factory=list)
