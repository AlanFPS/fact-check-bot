"""OpenAI-compatible LLM client and tolerant JSON parsing."""

import json
from typing import Any

from openai import NOT_GIVEN, APIConnectionError, APIError, APITimeoutError, OpenAI
from pydantic import ValidationError

from factcheckbot.config import Settings
from factcheckbot.logging_setup import get_logger
from factcheckbot.models import Evidence, FactCheckResult, Verdict
from factcheckbot.prompts import (
    CLAIM_EXTRACTION_SYSTEM,
    CLAIM_EXTRACTION_USER_TEMPLATE,
    VERDICT_JSON_SCHEMA,
    VERDICT_SYSTEM,
    VERDICT_USER_TEMPLATE,
    build_evidence_block,
)

logger = get_logger(__name__)


class LlmError(Exception):
    """Raised when the LLM endpoint cannot be reached."""


class LlmClient:
    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_seconds,
        )

    def extract_claim(self, raw_text: str) -> str:
        user = CLAIM_EXTRACTION_USER_TEMPLATE.format(raw_text=raw_text)
        raw = self._chat(CLAIM_EXTRACTION_SYSTEM, user, json_mode=True)
        try:
            data = _extract_json_object(raw)
        except json.JSONDecodeError:
            return raw_text.strip()
        claim = data.get("claim")
        return claim.strip() if isinstance(claim, str) else raw_text.strip()

    def fact_check(self, claim: str, evidence: list[Evidence]) -> FactCheckResult:
        base_user = VERDICT_USER_TEMPLATE.format(
            claim=claim,
            evidence_block=build_evidence_block(evidence),
            schema=json.dumps(VERDICT_JSON_SCHEMA),
        )
        user = base_user
        for attempt in range(self._settings.llm_max_retries + 1):
            raw = self._chat(VERDICT_SYSTEM, user, json_mode=True)
            try:
                data = _extract_json_object(raw)
                result = FactCheckResult.model_validate(data)
                valid_sources = [idx for idx in result.cited_sources if idx <= len(evidence)]
                return result.model_copy(update={"cited_sources": valid_sources})
            except (json.JSONDecodeError, ValidationError):
                logger.debug("Invalid LLM JSON response: %s", raw)
                if attempt == self._settings.llm_max_retries:
                    break
                user = (
                    f"{base_user}\n\nYour previous reply was not valid JSON matching the schema. "
                    "Return ONLY the JSON object."
                )
        return FactCheckResult(
            verdict=Verdict.UNVERIFIABLE,
            confidence=0.0,
            reasoning="The model did not return a parseable verdict.",
            cited_sources=[],
        )

    def _chat(self, system: str, user: str, *, json_mode: bool) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self._settings.llm_temperature,
                max_tokens=self._settings.llm_max_tokens,
                response_format={"type": "json_object"} if json_mode else NOT_GIVEN,
            )
        except (APIConnectionError, APITimeoutError, APIError) as exc:
            raise LlmError(f"LLM unavailable: {exc}") from exc
        return response.choices[0].message.content or ""


def _extract_json_object(text: str) -> dict[str, Any]:
    candidates = [text, _strip_code_fence(text)]
    balanced = _first_balanced_object(text)
    if balanced is not None:
        candidates.append(balanced)

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise json.JSONDecodeError("No JSON object found", text, 0)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None
