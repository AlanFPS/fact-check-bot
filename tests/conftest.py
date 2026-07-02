import pytest

from factcheckbot.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        reddit_client_id="client",
        reddit_client_secret="secret",
        reddit_username="factbot",
        reddit_password="password",
        seen_db_path=str(tmp_path / "seen.sqlite3"),
        dry_run=True,
        poll_sleep_seconds=0,
    )
