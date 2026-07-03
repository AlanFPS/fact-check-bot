from factcheckbot import reddit_client
from factcheckbot.reddit_client import fetch_unread_mentions, has_own_reply
from tests.fixtures import FakeComment, FakeReply


class FakePrivateMessage:
    body = "!factcheck private message"


class FakeInbox:
    def __init__(self, items):
        self.items = items

    def unread(self, limit: int):
        return self.items[:limit]


class FakeReddit:
    def __init__(self, items):
        self.inbox = FakeInbox(items)


def test_fetch_unread_mentions_filters_to_comments(monkeypatch):
    comment = FakeComment("!factcheck public comment")
    private_message = FakePrivateMessage()
    monkeypatch.setattr(reddit_client.praw.models, "Comment", FakeComment)

    mentions = fetch_unread_mentions(FakeReddit([comment, private_message]))

    assert mentions == [comment]


def test_has_own_reply_detects_bot_reply():
    comment = FakeComment(
        "!factcheck claim",
        replies=[FakeReply.by("other"), FakeReply.by("FactBot")],
    )

    assert has_own_reply(comment, "factbot") == "yes"
    assert comment.refreshed


def test_has_own_reply_returns_no_when_refresh_succeeds_without_bot_reply():
    comment = FakeComment("!factcheck claim", replies=[FakeReply.by("other")])

    assert has_own_reply(comment, "factbot") == "no"


def test_has_own_reply_returns_unknown_on_error():
    class BrokenComment:
        def refresh(self):
            raise RuntimeError("boom")

    assert has_own_reply(BrokenComment(), "factbot") == "unknown"
