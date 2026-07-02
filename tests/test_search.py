from factcheckbot.search import EvidenceSearcher
from tests.fixtures import CANNED_DDGS_RESULTS


class FakeDDGS:
    calls = 0
    timeout = None

    def __init__(
        self,
        results=None,
        raises: Exception | None = None,
        timeout: float | None = None,
    ) -> None:
        self.results = results if results is not None else CANNED_DDGS_RESULTS
        self.raises = raises
        FakeDDGS.timeout = timeout

    def text(self, *args, **kwargs):
        FakeDDGS.calls += 1
        if self.raises:
            raise self.raises
        return self.results


def test_search_maps_truncates_and_dedupes(settings):
    settings.search_snippet_chars = 8
    settings.search_timeout_seconds = 3.5
    searcher = EvidenceSearcher(settings, ddgs_factory=FakeDDGS)

    evidence = searcher.search("claim")

    assert [item.index for item in evidence] == [1, 2]
    assert evidence[0].title == "Source one"
    assert evidence[0].url == "https://example.com/one"
    assert evidence[0].snippet.endswith("…")
    assert FakeDDGS.timeout == 3.5


def test_empty_query_does_not_call_ddgs(settings):
    FakeDDGS.calls = 0
    searcher = EvidenceSearcher(settings, ddgs_factory=FakeDDGS)

    assert searcher.search("") == []
    assert FakeDDGS.calls == 0


def test_search_exception_returns_empty(settings, caplog):
    searcher = EvidenceSearcher(
        settings,
        ddgs_factory=lambda **kwargs: FakeDDGS(raises=RuntimeError("boom"), **kwargs),
    )

    assert searcher.search("claim") == []
    assert "Search failed" in caplog.text


def test_missing_keys_default_to_empty(settings):
    searcher = EvidenceSearcher(
        settings,
        ddgs_factory=lambda **kwargs: FakeDDGS(results=[{}], **kwargs),
    )

    evidence = searcher.search("claim")

    assert evidence[0].title == ""
    assert evidence[0].url == ""
    assert evidence[0].snippet == ""
