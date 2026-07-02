from factcheckbot import reddit_client
from factcheckbot.reddit_client import fetch_unread_mentions
from tests.fixtures import FakeComment


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
