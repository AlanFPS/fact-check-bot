import pytest

from factcheckbot import bot as bot_module
from factcheckbot.bot import Bot
from factcheckbot.llm import LlmError
from factcheckbot.models import FactCheckResult, TriggerContext, Verdict
from factcheckbot.pipeline import Pipeline
from factcheckbot.rate_limit import RateLimiter
from factcheckbot.seen_store import SeenStore
from tests.fixtures import CANNED_EVIDENCE, FakeComment


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

    result, evidence = pipeline.run("claim")

    assert result.verdict == Verdict.TRUE
    assert evidence == CANNED_EVIDENCE
    assert searcher.queries == ["claim"]
    assert llm.fact_check_calls == [("claim", CANNED_EVIDENCE)]


def test_run_propagates_llm_error(settings):
    pipeline = Pipeline(settings, FakeSearcher(), FakeLlm(raises=True))

    with pytest.raises(LlmError):
        pipeline.run("claim")


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
