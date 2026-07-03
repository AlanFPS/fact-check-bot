import httpx

from factcheckbot.google_factcheck import GoogleFactCheckClient, _map_claim

FULL_CLAIM = {
    "text": "The earth is flat.",
    "claimant": "Someone",
    "claimReview": [
        {
            "publisher": {"name": "Fact Publisher", "site": "publisher.example"},
            "textualRating": "False",
            "url": "https://example.com/fact-check",
            "title": "Earth fact check",
            "reviewDate": "2026-01-01",
        }
    ],
}


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class FakeHttpxClient:
    def __init__(self, response: FakeResponse | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[dict] = []

    def get(self, url: str, *, params: dict, timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        assert self.response is not None
        return self.response


def test_map_claim_full_claim():
    claim = _map_claim(FULL_CLAIM)

    assert claim is not None
    assert claim.text == "The earth is flat."
    assert claim.claimant == "Someone"
    assert claim.reviews[0].publisher == "Fact Publisher"
    assert claim.reviews[0].textual_rating == "False"
    assert claim.reviews[0].url == "https://example.com/fact-check"
    assert claim.reviews[0].title == "Earth fact check"
    assert claim.reviews[0].review_date == "2026-01-01"


def test_map_claim_missing_fields_and_non_http_review_drop():
    claim = _map_claim(
        {
            "text": "A claim.",
            "claimReview": [
                {"publisher": {"site": "site.example"}, "url": "ftp://example.com/bad"},
                {"publisher": {}, "url": "https://example.com/good"},
            ],
        }
    )

    assert claim is not None
    assert len(claim.reviews) == 1
    assert claim.reviews[0].publisher == "Unknown"
    assert claim.reviews[0].textual_rating == ""


def test_map_claim_drops_claims_without_usable_reviews():
    assert _map_claim({"text": "A claim.", "claimReview": []}) is None
    assert _map_claim({"text": "", "claimReview": [{"url": "https://example.com"}]}) is None
    assert _map_claim({"text": "A claim.", "claimReview": [{"url": "javascript:alert(1)"}]}) is None


def test_search_no_key_returns_empty_without_http_call(settings):
    settings.google_factcheck_api_key = None
    fake_client = FakeHttpxClient(FakeResponse(200, {"claims": [FULL_CLAIM]}))
    client = GoogleFactCheckClient(settings, client=fake_client)

    assert not client.enabled
    assert client.search("claim") == []
    assert fake_client.calls == []


def test_search_empty_query_returns_empty(settings):
    settings.google_factcheck_api_key = "key"
    fake_client = FakeHttpxClient(FakeResponse(200, {"claims": [FULL_CLAIM]}))
    client = GoogleFactCheckClient(settings, client=fake_client)

    assert client.search("") == []
    assert fake_client.calls == []


def test_search_happy_path_maps_and_truncates(settings):
    settings.google_factcheck_api_key = "key"
    settings.google_factcheck_max_claims = 1
    settings.google_factcheck_language = "en-US"
    settings.google_factcheck_timeout_seconds = 4.5
    payload = {"claims": [FULL_CLAIM, {**FULL_CLAIM, "text": "Second claim."}]}
    fake_client = FakeHttpxClient(FakeResponse(200, payload))
    client = GoogleFactCheckClient(settings, client=fake_client)

    claims = client.search("earth flat")

    assert len(claims) == 1
    assert claims[0].text == "The earth is flat."
    assert fake_client.calls == [
        {
            "url": GoogleFactCheckClient.ENDPOINT,
            "params": {
                "query": "earth flat",
                "key": "key",
                "languageCode": "en-US",
                "pageSize": 1,
            },
            "timeout": 4.5,
        }
    ]


def test_search_non_200_returns_empty(settings):
    settings.google_factcheck_api_key = "key"
    client = GoogleFactCheckClient(settings, client=FakeHttpxClient(FakeResponse(403)))

    assert client.search("claim") == []


def test_search_timeout_or_exception_returns_empty(settings):
    settings.google_factcheck_api_key = "key"
    request = httpx.Request("GET", GoogleFactCheckClient.ENDPOINT)
    fake_client = FakeHttpxClient(exc=httpx.TimeoutException("timeout", request=request))
    client = GoogleFactCheckClient(settings, client=fake_client)

    assert client.search("claim") == []


def test_search_exception_log_does_not_include_api_key(settings, caplog):
    settings.google_factcheck_api_key = "secret-test-key"
    fake_client = FakeHttpxClient(exc=RuntimeError("boom key=secret-test-key"))
    client = GoogleFactCheckClient(settings, client=fake_client)

    assert client.search("claim") == []
    assert "RuntimeError" in caplog.text
    assert "secret-test-key" not in caplog.text


def test_search_skips_malformed_claim_but_keeps_valid_claim(settings):
    settings.google_factcheck_api_key = "key"
    payload = {
        "claims": [
            {"text": "Malformed claim.", "claimReview": "not a list"},
            {**FULL_CLAIM, "text": "Valid claim."},
        ]
    }
    client = GoogleFactCheckClient(settings, client=FakeHttpxClient(FakeResponse(200, payload)))

    claims = client.search("claim")

    assert len(claims) == 1
    assert claims[0].text == "Valid claim."
