from dataclasses import dataclass
from typing import Any

from factcheckbot.models import Evidence

CANNED_DDGS_RESULTS = [
    {"title": "Source one", "href": "https://example.com/one", "body": "First source body."},
    {"title": "Source two", "href": "https://example.com/two", "body": "Second source body."},
    {"title": "Duplicate", "href": "https://example.com/one", "body": "Duplicate body."},
]

CANNED_LLM_JSON = (
    '{"verdict":"FALSE","confidence":1.2,"reasoning":"Evidence contradicts the claim.",'
    '"cited_sources":[1,2,2,0,99]}'
)

CANNED_EVIDENCE = [
    Evidence(index=1, title="Source one", url="https://example.com/one", snippet="One."),
    Evidence(index=2, title="Source two", url="https://example.com/two", snippet="Two."),
]


@dataclass
class FakeAuthor:
    name: str

    def __str__(self) -> str:
        return self.name


class FakeComment:
    def __init__(
        self,
        body: str,
        *,
        fullname: str = "t1_comment",
        author: str | None = "alice",
        parent: Any | None = None,
        fail_reply: bool = False,
    ) -> None:
        self.body = body
        self.fullname = fullname
        self.author = FakeAuthor(author) if author is not None else None
        self.permalink = f"/r/test/comments/{fullname}"
        self._parent = parent
        self.fail_reply = fail_reply
        self.replies: list[str] = []
        self.read = False

    def parent(self) -> Any:
        return self._parent

    def reply(self, text: str) -> None:
        if self.fail_reply:
            raise RuntimeError("reply failed")
        self.replies.append(text)

    def mark_read(self) -> None:
        self.read = True


class FakeSubmission:
    def __init__(self, title: str, selftext: str = "") -> None:
        self.title = title
        self.selftext = selftext
