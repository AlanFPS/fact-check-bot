import json

import httpx
import pytest
from openai import APIConnectionError
from pydantic import ValidationError

from factcheckbot.llm import LlmClient, LlmError, _extract_json_object
from factcheckbot.models import FactCheckResult, Verdict
from tests.fixtures import CANNED_EVIDENCE, CANNED_LLM_JSON


class FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self, responses: list[str] | None = None, exc: Exception | None = None) -> None:
        self.responses = responses or []
        self.exc = exc
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.exc:
            raise self.exc
        return FakeResponse(self.responses.pop(0))


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = FakeChat(completions)


def test_extract_json_object_variants():
    assert _extract_json_object('{"a": 1}') == {"a": 1}
    assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json_object('thinking...\n{"a": {"b": 2}}\ntrailing') == {"a": {"b": 2}}
    assert _extract_json_object('prefix {"a": "brace } inside"} junk') == {"a": "brace } inside"}
    with pytest.raises(json.JSONDecodeError):
        _extract_json_object("not json")


def test_fact_check_happy_path_clamps_and_filters_sources(settings):
    completions = FakeCompletions([CANNED_LLM_JSON])
    client = LlmClient(settings, client=FakeClient(completions))

    result = client.fact_check("claim", CANNED_EVIDENCE)

    assert result.verdict == Verdict.FALSE
    assert result.confidence == 1.0
    assert result.cited_sources == [1, 2]


def test_fact_check_retries_bad_json(settings):
    completions = FakeCompletions(["garbage", CANNED_LLM_JSON])
    client = LlmClient(settings, client=FakeClient(completions))

    result = client.fact_check("claim", CANNED_EVIDENCE)

    assert result.verdict == Verdict.FALSE
    assert completions.calls == 2


def test_non_finite_confidence_is_rejected_and_retried(settings):
    bad = (
        '{"verdict":"FALSE","confidence":NaN,"reasoning":"Bad confidence.",'
        '"cited_sources":[1]}'
    )
    completions = FakeCompletions([bad, CANNED_LLM_JSON])
    client = LlmClient(settings, client=FakeClient(completions))

    result = client.fact_check("claim", CANNED_EVIDENCE)

    assert result.verdict == Verdict.FALSE
    assert completions.calls == 2


def test_fact_check_result_rejects_non_finite_confidence():
    with pytest.raises(ValidationError):
        FactCheckResult(
            verdict=Verdict.FALSE,
            confidence=float("nan"),
            reasoning="Bad confidence.",
            cited_sources=[],
        )


def test_fact_check_exhausted_retries_returns_default(settings):
    settings.llm_max_retries = 1
    completions = FakeCompletions(["garbage", "still garbage"])
    client = LlmClient(settings, client=FakeClient(completions))

    result = client.fact_check("claim", CANNED_EVIDENCE)

    assert result.verdict == Verdict.UNVERIFIABLE
    assert result.confidence == 0.0


def test_connection_error_raises_llm_error(settings):
    request = httpx.Request("POST", "http://example.test")
    completions = FakeCompletions(exc=APIConnectionError(request=request))
    client = LlmClient(settings, client=FakeClient(completions))

    with pytest.raises(LlmError):
        client.fact_check("claim", CANNED_EVIDENCE)


def test_extract_claim_parses_or_falls_back(settings):
    completions = FakeCompletions(['{"claim":"The moon exists."}', "garbage"])
    client = LlmClient(settings, client=FakeClient(completions))

    assert client.extract_claim("raw text") == "The moon exists."
    assert client.extract_claim("raw text") == "raw text"
