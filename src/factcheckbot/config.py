"""Application settings loaded from environment variables."""

import re
from typing import Annotated, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    reddit_client_id: str
    reddit_client_secret: str
    reddit_username: str
    reddit_password: str
    reddit_user_agent: str | None = None

    bot_trigger: str = "!factcheck"
    monitored_subreddits: Annotated[list[str], NoDecode] = ["testingground4bots"]
    enable_comment_stream: bool = True
    enable_inbox_mentions: bool = True

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3:4b-instruct"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 700
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    search_max_results: int = 5
    search_snippet_chars: int = 500
    search_region: str = "us-en"
    search_timelimit: str | None = None
    search_timeout_seconds: float = 15.0

    google_factcheck_api_key: str | None = None
    google_factcheck_max_claims: int = 3
    google_factcheck_language: str = "en"
    google_factcheck_timeout_seconds: float = 10.0

    max_claim_chars: int = 500
    max_reply_chars: int = 9500
    rate_limit_per_user_per_hour: int = 3
    rate_limit_global_per_hour: int = 30

    seen_db_path: str = "data/seen.sqlite3"
    dry_run: bool = True
    ignore_bots: bool = True
    log_level: str = "INFO"
    log_json: bool = False
    poll_sleep_seconds: float = 10.0

    @field_validator("monitored_subreddits", mode="before")
    @classmethod
    def parse_subreddits(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip().lower() for part in re.split(r"[,+]", value) if part.strip()]
        return value

    @field_validator("search_timelimit", mode="before")
    @classmethod
    def parse_search_timelimit(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() in {"", "none"}:
            return None
        return value

    @field_validator("google_factcheck_api_key", mode="before")
    @classmethod
    def parse_google_factcheck_api_key(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @model_validator(mode="after")
    def finalize_settings(self) -> Self:
        if self.reddit_user_agent is None:
            self.reddit_user_agent = f"fact-check-bot/1.0 (by u/{self.reddit_username})"
        self.max_reply_chars = min(self.max_reply_chars, 10000)
        return self
