"""In-process counters for lightweight observability."""

from dataclasses import dataclass, field


@dataclass
class Metrics:
    items_seen: int = 0
    triggers_matched: int = 0
    replies_posted: int = 0
    dry_run_replies: int = 0
    google_hits: int = 0
    llm_verdicts: int = 0
    search_failures: int = 0
    google_failures: int = 0
    llm_failures: int = 0
    rate_limited: int = 0
    verdict_counts: dict[str, int] = field(default_factory=dict)

    def record_verdict(self, verdict: str) -> None:
        self.verdict_counts[verdict] = self.verdict_counts.get(verdict, 0) + 1

    def as_log_extra(self) -> dict[str, object]:
        return {
            "items_seen": self.items_seen,
            "triggers_matched": self.triggers_matched,
            "replies_posted": self.replies_posted,
            "dry_run_replies": self.dry_run_replies,
            "google_hits": self.google_hits,
            "llm_verdicts": self.llm_verdicts,
            "search_failures": self.search_failures,
            "google_failures": self.google_failures,
            "llm_failures": self.llm_failures,
            "rate_limited": self.rate_limited,
            "verdict_counts": dict(self.verdict_counts),
        }
