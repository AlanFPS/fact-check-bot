"""Command-line entrypoint."""

import signal

from factcheckbot.bot import Bot
from factcheckbot.config import Settings
from factcheckbot.google_factcheck import GoogleFactCheckClient
from factcheckbot.llm import LlmClient
from factcheckbot.logging_setup import configure, get_logger
from factcheckbot.metrics import Metrics
from factcheckbot.rate_limit import RateLimiter
from factcheckbot.reddit_client import build_reddit
from factcheckbot.search import EvidenceSearcher
from factcheckbot.seen_store import SeenStore


def main() -> int:
    settings = Settings()
    configure(settings)
    logger = get_logger(__name__)

    seen = SeenStore(settings.seen_db_path)
    limiter = RateLimiter(
        seen,
        settings.rate_limit_per_user_per_hour,
        settings.rate_limit_global_per_hour,
    )
    metrics = Metrics()
    searcher = EvidenceSearcher(settings, metrics=metrics)
    llm = LlmClient(settings)
    google = (
        GoogleFactCheckClient(settings, metrics=metrics)
        if settings.google_factcheck_api_key
        else None
    )
    reddit = build_reddit(settings)
    bot = Bot(settings, reddit, searcher, llm, seen, limiter, google=google, metrics=metrics)

    def _request_stop(_signum: int, _frame: object) -> None:
        logger.info("Shutdown requested")
        bot.request_stop()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
        bot.request_stop()
    except Exception:
        logger.exception("Bot crashed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
