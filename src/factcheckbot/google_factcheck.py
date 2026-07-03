"""Google Fact Check Tools API client."""

from typing import Any
from urllib.parse import urlparse

import httpx

from factcheckbot.config import Settings
from factcheckbot.logging_setup import get_logger
from factcheckbot.models import GoogleClaim, GoogleReview

logger = get_logger(__name__)


class GoogleFactCheckClient:
    ENDPOINT = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.google_factcheck_timeout_seconds)

    @property
    def enabled(self) -> bool:
        return bool(self._settings.google_factcheck_api_key)

    def search(self, query: str) -> list[GoogleClaim]:
        if not self.enabled or not query:
            return []
        try:
            response = self._client.get(
                self.ENDPOINT,
                params={
                    "query": query,
                    "key": self._settings.google_factcheck_api_key,
                    "languageCode": self._settings.google_factcheck_language,
                    "pageSize": self._settings.google_factcheck_max_claims,
                },
                timeout=self._settings.google_factcheck_timeout_seconds,
            )
            if response.status_code != 200:
                logger.warning("Google fact-check failed with status %s", response.status_code)
                return []
            raw_claims = response.json().get("claims") or []
            claims: list[GoogleClaim] = []
            for raw in raw_claims:
                if not isinstance(raw, dict):
                    continue
                try:
                    claim = _map_claim(raw)
                except Exception:
                    continue
                if claim is not None:
                    claims.append(claim)
            return [claim for claim in claims if claim is not None][
                : self._settings.google_factcheck_max_claims
            ]
        except Exception as exc:
            logger.warning("Google fact-check failed (%s)", type(exc).__name__)
            return []


def _map_claim(raw: dict[str, Any]) -> GoogleClaim | None:
    text = str(raw.get("text") or "").strip()
    if not text:
        return None

    reviews: list[GoogleReview] = []
    raw_reviews = raw.get("claimReview") or []
    if not isinstance(raw_reviews, list):
        return None

    for review in raw_reviews:
        if not isinstance(review, dict):
            continue
        url = str(review.get("url") or "").strip()
        if not _is_http_url(url):
            continue
        publisher = review.get("publisher") or {}
        if not isinstance(publisher, dict):
            publisher = {}
        reviews.append(
            GoogleReview(
                publisher=str(
                    publisher.get("name") or publisher.get("site") or "Unknown"
                ).strip(),
                textual_rating=str(review.get("textualRating") or "").strip(),
                url=url,
                title=_optional_str(review.get("title")),
                review_date=_optional_str(review.get("reviewDate")),
            )
        )

    if not reviews:
        return None
    return GoogleClaim(
        text=text,
        claimant=_optional_str(raw.get("claimant")),
        reviews=reviews,
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_http_url(url: str) -> bool:
    return urlparse(url).scheme in {"http", "https"}
