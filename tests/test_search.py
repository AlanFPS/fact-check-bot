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


class FakeExtractor:
    timeout = None
    extract_timeout = None

    def __init__(
        self,
        texts: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> None:
        self.texts = texts or {}
        self.calls: list[str] = []
        FakeExtractor.timeout = timeout

    def extract(self, url: str, fmt: str = "text_plain", timeout: float | None = None):
        self.calls.append(url)
        FakeExtractor.extract_timeout = timeout
        return self.texts.get(url, "")


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


def test_fulltext_enrichment_disabled_by_default(settings):
    extractor = FakeExtractor({"https://example.com/one": "Full article text."})
    searcher = EvidenceSearcher(
        settings,
        ddgs_factory=FakeDDGS,
        extractor_factory=lambda **kwargs: extractor,
    )

    evidence = searcher.search("claim")

    assert evidence[0].snippet == "First source body."
    assert extractor.calls == []


def test_fulltext_enrichment_enabled_for_top_http_results(settings):
    settings.enable_fulltext_evidence = True
    settings.evidence_fetch_top_n = 1
    settings.evidence_fetch_timeout_seconds = 6.0
    settings.evidence_fulltext_chars = 18
    extractor = FakeExtractor({"https://example.com/one": "Full article text goes here."})
    searcher = EvidenceSearcher(
        settings,
        ddgs_factory=FakeDDGS,
        extractor_factory=lambda **kwargs: extractor,
    )

    evidence = searcher.search("claim")

    assert evidence[0].snippet == "Full article…"
    assert evidence[1].snippet == "Second source body."
    assert extractor.calls == ["https://example.com/one"]
    assert FakeExtractor.extract_timeout == 6.0


def test_fulltext_enrichment_falls_back_when_extract_timeout_kw_unsupported(settings):
    class NoTimeoutExtractor:
        def __init__(self) -> None:
            self.calls = 0

        def extract(self, url: str, fmt: str = "text_plain"):
            self.calls += 1
            return "Full article text."

    settings.enable_fulltext_evidence = True
    settings.evidence_fetch_top_n = 1
    extractor = NoTimeoutExtractor()
    searcher = EvidenceSearcher(
        settings,
        ddgs_factory=FakeDDGS,
        extractor_factory=lambda **kwargs: extractor,
    )

    evidence = searcher.search("claim")

    assert evidence[0].snippet == "Full article text."
    assert extractor.calls == 1


def test_fulltext_enrichment_degrades_when_extract_missing(settings):
    settings.enable_fulltext_evidence = True
    searcher = EvidenceSearcher(settings, ddgs_factory=FakeDDGS, extractor_factory=FakeDDGS)

    evidence = searcher.search("claim")

    assert evidence[0].snippet == "First source body."


def test_fulltext_enrichment_ignores_junk_extract_results(settings):
    class JunkExtractor:
        def __init__(self, value: object) -> None:
            self.value = value

        def extract(self, url: str, fmt: str = "text_plain", timeout: float | None = None):
            return self.value

    settings.enable_fulltext_evidence = True
    settings.evidence_fetch_top_n = 1
    junk_values = [
        ["not", "text"],
        123,
        None,
        {"unexpected": "value"},
    ]

    for value in junk_values:
        searcher = EvidenceSearcher(
            settings,
            ddgs_factory=FakeDDGS,
            extractor_factory=lambda value=value, **kwargs: JunkExtractor(value),
        )

        evidence = searcher.search("claim")

        assert evidence[0].snippet == "First source body."


def test_fulltext_enrichment_keeps_original_snippet_when_extract_raises(settings):
    class RaisingExtractor:
        def extract(self, url: str, fmt: str = "text_plain", timeout: float | None = None):
            raise RuntimeError("boom")

    settings.enable_fulltext_evidence = True
    settings.evidence_fetch_top_n = 1
    searcher = EvidenceSearcher(
        settings,
        ddgs_factory=FakeDDGS,
        extractor_factory=lambda **kwargs: RaisingExtractor(),
    )

    evidence = searcher.search("claim")

    assert evidence[0].snippet == "First source body."
