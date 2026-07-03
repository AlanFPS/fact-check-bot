import logging

import pytest

from factcheckbot import bot as bot_module
from factcheckbot.bot import Bot
from factcheckbot.llm import LlmError
from factcheckbot.metrics import Metrics
from factcheckbot.models import FactCheckResult, GoogleClaim, GoogleReview, TriggerContext, Verdict
from factcheckbot.pipeline import Pipeline
from factcheckbot.rate_limit import RateLimiter
from factcheckbot.seen_store import SeenStore
from tests.fixtures import CANNED_EVIDENCE, FakeComment, FakeReply


class FakeSearcher:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str):
        self.queries.append(query)
        return CANNED_EVIDENCE


class FakeLlm:
    def __init__(self, *, raises: bool = False) -> None:
        self.extract_calls: list[str] = []
        self.fact_check_calls: list[tuple[str, object]] = []
        self.raises = raises

    def extract_claim(self, raw_text: str) -> str:
        self.extract_calls.append(raw_text)
        return "Extracted claim."

    def fact_check(self, claim: str, evidence):
        if self.raises:
            raise LlmError("down")
        self.fact_check_calls.append((claim, evidence))
        return FactCheckResult(
            verdict=Verdict.TRUE,
            confidence=0.9,
            reasoning="The evidence supports the claim.",
            cited_sources=[1],
        )


GOOGLE_CLAIMS = [
    GoogleClaim(
        text="The earth is flat.",
        claimant="Someone",
        reviews=[
            GoogleReview(
                publisher="Fact Publisher",
                textual_rating="False",
                url="https://example.com/fact-check",
            )
        ],
    )
]


class FakeGoogle:
    def __init__(self, *, enabled: bool = True, claims=None) -> None:
        self.enabled = enabled
        self.claims = claims if claims is not None else GOOGLE_CLAIMS
        self.queries: list[str] = []

    def search(self, query: str):
        self.queries.append(query)
        return self.claims


def ctx(inline_query: str = "") -> TriggerContext:
    return TriggerContext(
        item_id="t1_item",
        author="alice",
        inline_query=inline_query,
        permalink="/r/test/comments/t1_item",
        source="comment_stream",
    )


def test_resolve_claim_inline_query_does_not_fetch_parent(settings):
    llm = FakeLlm()
    pipeline = Pipeline(settings, FakeSearcher(), llm)

    claim = pipeline.resolve_claim(ctx("  'Inline claim.'"), parent_text_getter=pytest.fail)

    assert claim == "Inline claim."
    assert llm.extract_calls == []


def test_resolve_claim_bare_trigger_uses_parent(settings):
    llm = FakeLlm()
    pipeline = Pipeline(settings, FakeSearcher(), llm)

    claim = pipeline.resolve_claim(ctx(), parent_text_getter=lambda: "Parent text.")

    assert claim == "Extracted claim."
    assert llm.extract_calls == ["Parent text."]


def test_resolve_claim_without_parent_returns_empty(settings):
    pipeline = Pipeline(settings, FakeSearcher(), FakeLlm())

    assert pipeline.resolve_claim(ctx(), parent_text_getter=lambda: None) == ""


def test_run_wires_search_and_llm(settings):
    searcher = FakeSearcher()
    llm = FakeLlm()
    pipeline = Pipeline(settings, searcher, llm)

    outcome = pipeline.run("claim")

    assert outcome.source == "llm"
    assert outcome.claim == "claim"
    assert outcome.llm_result is not None
    assert outcome.llm_result.verdict == Verdict.TRUE
    assert outcome.evidence == CANNED_EVIDENCE
    assert searcher.queries == ["claim"]
    assert llm.fact_check_calls == [("claim", CANNED_EVIDENCE)]


def test_run_google_hits_skip_search_and_llm(settings):
    searcher = FakeSearcher()
    llm = FakeLlm()
    google = FakeGoogle(claims=GOOGLE_CLAIMS)
    pipeline = Pipeline(settings, searcher, llm, google)

    outcome = pipeline.run("claim")

    assert outcome.source == "google"
    assert outcome.claim == "claim"
    assert outcome.google_claims == GOOGLE_CLAIMS
    assert google.queries == ["claim"]
    assert searcher.queries == []
    assert llm.fact_check_calls == []


def test_run_google_no_hits_falls_back_to_llm(settings):
    searcher = FakeSearcher()
    llm = FakeLlm()
    google = FakeGoogle(claims=[])
    pipeline = Pipeline(settings, searcher, llm, google)

    outcome = pipeline.run("claim")

    assert outcome.source == "llm"
    assert google.queries == ["claim"]
    assert searcher.queries == ["claim"]
    assert llm.fact_check_calls == [("claim", CANNED_EVIDENCE)]


def test_run_google_disabled_falls_back_without_call(settings):
    searcher = FakeSearcher()
    llm = FakeLlm()
    google = FakeGoogle(enabled=False)
    pipeline = Pipeline(settings, searcher, llm, google)

    outcome = pipeline.run("claim")

    assert outcome.source == "llm"
    assert google.queries == []
    assert searcher.queries == ["claim"]
    assert llm.fact_check_calls == [("claim", CANNED_EVIDENCE)]


def test_run_google_error_empty_result_falls_back(settings):
    searcher = FakeSearcher()
    llm = FakeLlm()
    google = FakeGoogle(claims=[])
    pipeline = Pipeline(settings, searcher, llm, google)

    outcome = pipeline.run("claim")

    assert outcome.source == "llm"
    assert searcher.queries == ["claim"]
    assert llm.fact_check_calls == [("claim", CANNED_EVIDENCE)]


def test_run_propagates_llm_error(settings):
    pipeline = Pipeline(settings, FakeSearcher(), FakeLlm(raises=True))

    with pytest.raises(LlmError):
        pipeline.run("claim")


def test_run_cache_hit_skips_search_and_llm(settings):
    settings.enable_verdict_cache = True
    store = SeenStore(":memory:")
    cached = Pipeline(settings, FakeSearcher(), FakeLlm()).run("cached claim")
    store.store_cached_verdict(
        "unused",
        cached.source,
        cached.model_dump_json(),
        now=1000.0,
    )
    # Store under the real key by running once through a cache-enabled pipeline.
    searcher = FakeSearcher()
    llm = FakeLlm()
    pipeline = Pipeline(settings, searcher, llm, cache_store=store, now=lambda: 1000.0)
    first = pipeline.run("cached claim")

    second_searcher = FakeSearcher()
    second_llm = FakeLlm()
    second_pipeline = Pipeline(
        settings,
        second_searcher,
        second_llm,
        cache_store=store,
        now=lambda: 1001.0,
    )
    second = second_pipeline.run("cached claim")

    assert first.source == "llm"
    assert second.source == "llm"
    assert second_searcher.queries == []
    assert second_llm.fact_check_calls == []
    store.close()


def test_run_cache_expiry_recomputes(settings):
    settings.enable_verdict_cache = True
    settings.cache_ttl_seconds = 10
    store = SeenStore(":memory:")
    pipeline = Pipeline(settings, FakeSearcher(), FakeLlm(), cache_store=store, now=lambda: 1000.0)

    pipeline.run("claim")

    searcher = FakeSearcher()
    llm = FakeLlm()
    expired = Pipeline(settings, searcher, llm, cache_store=store, now=lambda: 1011.0)
    expired.run("claim")

    assert searcher.queries == ["claim"]
    assert llm.fact_check_calls == [("claim", CANNED_EVIDENCE)]
    store.close()


def test_run_cache_key_changes_when_google_tier_enabled(settings):
    settings.enable_verdict_cache = True
    store = SeenStore(":memory:")
    llm_pipeline = Pipeline(
        settings,
        FakeSearcher(),
        FakeLlm(),
        cache_store=store,
        now=lambda: 1000.0,
    )
    llm_pipeline.run("same claim")

    searcher = FakeSearcher()
    llm = FakeLlm()
    google = FakeGoogle(claims=GOOGLE_CLAIMS)
    google_pipeline = Pipeline(
        settings,
        searcher,
        llm,
        google,
        cache_store=store,
        now=lambda: 1001.0,
    )
    outcome = google_pipeline.run("same claim")

    assert outcome.source == "google"
    assert searcher.queries == []
    assert llm.fact_check_calls == []
    assert google.queries == ["same claim"]
    store.close()


def test_bot_handle_item_gatekeeping_and_happy_path(settings):
    store = SeenStore(":memory:")
    limiter = RateLimiter(store, 3, 30, now=lambda: 1000.0)
    bot = Bot(
        settings,
        reddit=None,
        searcher=FakeSearcher(),
        llm=FakeLlm(),
        seen=store,
        limiter=limiter,
    )

    seen_item = FakeComment("!factcheck claim", fullname="t1_seen")
    store.mark_seen("t1_seen")
    assert bot._handle_item(seen_item, "comment_stream")

    no_trigger = FakeComment("hello", fullname="t1_no_trigger")
    assert bot._handle_item(no_trigger, "comment_stream")
    assert store.is_seen("t1_no_trigger")

    self_item = FakeComment("!factcheck claim", fullname="t1_self", author=settings.reddit_username)
    assert bot._handle_item(self_item, "comment_stream")
    assert store.is_seen("t1_self")

    bot_item = FakeComment("!factcheck claim", fullname="t1_bot", author="helperbot")
    assert bot._handle_item(bot_item, "comment_stream")
    assert store.is_seen("t1_bot")

    limiter.record("alice")
    limiter.record("alice")
    limiter.record("alice")
    limited = FakeComment("!factcheck claim", fullname="t1_limited", author="alice")
    assert bot._handle_item(limited, "comment_stream")
    assert store.is_seen("t1_limited")

    happy = FakeComment("!factcheck claim", fullname="t1_happy", author="bob")
    assert bot._handle_item(happy, "comment_stream")
    assert store.is_seen("t1_happy")
    assert store.list_pending() == []
    assert limiter.allow("bob") == (True, "")
    store.close()


def test_bot_handle_item_returns_false_for_retryable_llm_error(settings):
    store = SeenStore(":memory:")
    limiter = RateLimiter(store, 3, 30, now=lambda: 1000.0)
    bot = Bot(
        settings,
        reddit=None,
        searcher=FakeSearcher(),
        llm=FakeLlm(raises=True),
        seen=store,
        limiter=limiter,
    )
    item = FakeComment("!factcheck claim", fullname="t1_retry", author="alice")

    assert not bot._handle_item(item, "inbox_mention")
    assert not store.is_seen("t1_retry")
    store.close()


def test_bot_handle_item_returns_false_for_failed_reply(settings, monkeypatch):
    settings.dry_run = False
    store = SeenStore(":memory:")
    limiter = RateLimiter(store, 3, 30, now=lambda: 1000.0)
    bot = Bot(
        settings,
        reddit=None,
        searcher=FakeSearcher(),
        llm=FakeLlm(),
        seen=store,
        limiter=limiter,
    )
    monkeypatch.setattr(bot_module, "safe_reply", lambda *args, **kwargs: False)
    item = FakeComment("!factcheck claim", fullname="t1_reply_fail", author="alice")

    assert not bot._handle_item(item, "inbox_mention")
    assert not store.is_seen("t1_reply_fail")
    assert store.list_pending() == ["t1_reply_fail"]
    store.close()


def test_bot_reconcile_pending_marks_seen_when_own_reply_exists(settings):
    store = SeenStore(":memory:")
    store.mark_pending("t1_done")
    item = FakeComment("!factcheck claim", fullname="t1_done", replies=[FakeReply.by("factbot")])

    class FakeReddit:
        def comment(self, id: str):
            assert id == "done"
            return item

    bot = Bot(
        settings,
        reddit=FakeReddit(),
        searcher=FakeSearcher(),
        llm=FakeLlm(),
        seen=store,
        limiter=RateLimiter(store, 3, 30),
    )

    bot.reconcile_pending()

    assert store.is_seen("t1_done")
    assert store.list_pending() == []
    store.close()


def test_bot_reconcile_pending_clears_without_own_reply(settings):
    store = SeenStore(":memory:")
    store.mark_pending("t1_retry")

    class FakeReddit:
        def comment(self, id: str):
            return FakeComment("!factcheck claim", fullname=f"t1_{id}")

    bot = Bot(
        settings,
        reddit=FakeReddit(),
        searcher=FakeSearcher(),
        llm=FakeLlm(),
        seen=store,
        limiter=RateLimiter(store, 3, 30),
    )

    bot.reconcile_pending()

    assert not store.is_seen("t1_retry")
    assert store.list_pending() == []
    store.close()


def test_bot_reconcile_pending_keeps_unknown_when_refresh_fails(settings):
    store = SeenStore(":memory:")
    store.mark_pending("t1_unknown")

    class BrokenComment:
        def refresh(self):
            raise RuntimeError("reddit unavailable")

    class FakeReddit:
        def comment(self, id: str):
            return BrokenComment()

    bot = Bot(
        settings,
        reddit=FakeReddit(),
        searcher=FakeSearcher(),
        llm=FakeLlm(),
        seen=store,
        limiter=RateLimiter(store, 3, 30),
    )

    bot.reconcile_pending()

    assert not store.is_seen("t1_unknown")
    assert store.list_pending() == ["t1_unknown"]
    store.close()


def test_bot_reconcile_pending_keeps_unknown_when_item_load_fails(settings):
    store = SeenStore(":memory:")
    store.mark_pending("t1_missing")
    bot = Bot(
        settings,
        reddit=object(),
        searcher=FakeSearcher(),
        llm=FakeLlm(),
        seen=store,
        limiter=RateLimiter(store, 3, 30),
    )

    bot.reconcile_pending()

    assert store.list_pending() == ["t1_missing"]
    store.close()


def test_pending_inbox_with_existing_own_reply_skips_second_post(settings, monkeypatch):
    store = SeenStore(":memory:")
    store.mark_pending("t1_pending_inbox")
    item = FakeComment(
        "!factcheck claim",
        fullname="t1_pending_inbox",
        author="alice",
        replies=[FakeReply.by("factbot")],
    )
    bot = Bot(
        settings,
        reddit=None,
        searcher=FakeSearcher(),
        llm=FakeLlm(),
        seen=store,
        limiter=RateLimiter(store, 3, 30),
    )
    monkeypatch.setattr(
        bot_module,
        "safe_reply",
        lambda *args, **kwargs: pytest.fail("safe_reply should not be called"),
    )

    assert bot._handle_item(item, "inbox_mention")
    assert store.is_seen("t1_pending_inbox")
    assert store.list_pending() == []


def test_comment_stream_allowlist_blocks_unlisted_subreddit(settings, monkeypatch):
    settings.subreddit_allowlist = ["allowedsub"]
    store = SeenStore(":memory:")
    searcher = FakeSearcher()
    llm = FakeLlm()
    bot = Bot(
        settings,
        reddit=None,
        searcher=searcher,
        llm=llm,
        seen=store,
        limiter=RateLimiter(store, 3, 30),
    )
    monkeypatch.setattr(
        bot_module,
        "safe_reply",
        lambda *args, **kwargs: pytest.fail("safe_reply should not be called"),
    )
    item = FakeComment(
        "!factcheck claim",
        fullname="t1_blocked_sub",
        author="alice",
        subreddit="othersub",
    )

    assert bot._handle_item(item, "comment_stream")
    assert store.is_seen("t1_blocked_sub")
    assert searcher.queries == []
    assert llm.fact_check_calls == []
    store.close()


def test_allowlist_allows_matching_subreddit_and_inbox_bypasses(settings, monkeypatch):
    settings.subreddit_allowlist = ["allowedsub"]
    store = SeenStore(":memory:")
    calls: list[str] = []
    bot = Bot(
        settings,
        reddit=None,
        searcher=FakeSearcher(),
        llm=FakeLlm(),
        seen=store,
        limiter=RateLimiter(store, 3, 30),
    )
    monkeypatch.setattr(
        bot_module,
        "safe_reply",
        lambda item, text, **kwargs: calls.append(item.fullname) is None or True,
    )

    allowed = FakeComment(
        "!factcheck claim",
        fullname="t1_allowed_sub",
        author="alice",
        subreddit="allowedsub",
    )
    inbox = FakeComment(
        "!factcheck claim",
        fullname="t1_inbox_sub",
        author="bob",
        subreddit="othersub",
    )

    assert bot._handle_item(allowed, "comment_stream")
    assert bot._handle_item(inbox, "inbox_mention")
    assert calls == ["t1_allowed_sub", "t1_inbox_sub"]
    store.close()


def test_metrics_increment_and_interval_logging(settings, caplog):
    caplog.set_level(logging.INFO)
    current = 0.0
    metrics = Metrics()
    store = SeenStore(":memory:")
    bot = Bot(
        settings,
        reddit=None,
        searcher=FakeSearcher(),
        llm=FakeLlm(),
        seen=store,
        limiter=RateLimiter(store, 3, 30),
        metrics=metrics,
        now=lambda: current,
    )
    settings.metrics_log_interval_seconds = 10

    assert bot._handle_item(
        FakeComment("!factcheck claim", fullname="t1_metrics"),
        "comment_stream",
    )
    assert metrics.items_seen == 1
    assert metrics.triggers_matched == 1
    assert metrics.replies_posted == 0
    assert metrics.dry_run_replies == 1
    assert metrics.llm_verdicts == 1
    assert metrics.verdict_counts == {"TRUE": 1}

    caplog.clear()
    bot._maybe_log_metrics()
    assert not caplog.records

    current = 11.0
    bot._maybe_log_metrics()
    assert any(record.message == "metrics" for record in caplog.records)
    store.close()


def test_inbox_mark_read_depends_on_handle_result(settings, monkeypatch):
    settings.enable_comment_stream = False
    settings.enable_inbox_mentions = True
    item = FakeComment("!factcheck claim", fullname="t1_inbox_retry", author="alice")
    store = SeenStore(":memory:")
    limiter = RateLimiter(store, 3, 30, now=lambda: 1000.0)
    bot = Bot(
        settings,
        reddit=None,
        searcher=FakeSearcher(),
        llm=FakeLlm(raises=True),
        seen=store,
        limiter=limiter,
    )
    monkeypatch.setattr(bot_module, "fetch_unread_mentions", lambda reddit: [item])
    monkeypatch.setattr(bot_module.time, "sleep", lambda seconds: bot.request_stop())

    bot.run()

    assert not item.read
