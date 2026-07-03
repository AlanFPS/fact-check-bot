import pytest
from pydantic import ValidationError

from factcheckbot.config import Settings

REQUIRED_ENV = (
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USERNAME",
    "REDDIT_PASSWORD",
)


def test_missing_required_reddit_vars_raise(monkeypatch):
    for name in REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_env_parsing(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "client")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USERNAME", "FactBot")
    monkeypatch.setenv("REDDIT_PASSWORD", "password")
    monkeypatch.setenv("MONITORED_SUBREDDITS", "A,b+C")
    monkeypatch.setenv("SEARCH_TIMELIMIT", "none")
    monkeypatch.setenv("MAX_REPLY_CHARS", "12000")
    monkeypatch.setenv("GOOGLE_FACTCHECK_API_KEY", "  ")

    settings = Settings(_env_file=None)

    assert settings.monitored_subreddits == ["a", "b", "c"]
    assert settings.reddit_user_agent == "fact-check-bot/1.0 (by u/FactBot)"
    assert settings.search_timelimit is None
    assert settings.max_reply_chars == 10000
    assert settings.google_factcheck_api_key is None
    assert settings.google_factcheck_max_claims == 3
    assert settings.google_factcheck_language == "en"
    assert settings.google_factcheck_timeout_seconds == 10.0


def test_google_factcheck_api_key_kept(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "client")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USERNAME", "FactBot")
    monkeypatch.setenv("REDDIT_PASSWORD", "password")
    monkeypatch.setenv("GOOGLE_FACTCHECK_API_KEY", "google-key")

    settings = Settings(_env_file=None)

    assert settings.google_factcheck_api_key == "google-key"
