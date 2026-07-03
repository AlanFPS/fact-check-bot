"""PRAW helpers for Reddit I/O."""

from collections.abc import Iterator
from typing import Any, Literal

import praw
import praw.exceptions
import prawcore.exceptions

from factcheckbot.config import Settings

OwnReplyStatus = Literal["yes", "no", "unknown"]


def build_reddit(settings: Settings) -> praw.Reddit:
    reddit = praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        username=settings.reddit_username,
        password=settings.reddit_password,
        user_agent=settings.reddit_user_agent,
    )
    reddit.validate_on_submit = True
    return reddit


def iter_comment_stream(
    reddit: praw.Reddit,
    subreddits: list[str],
    pause_after: int | None = None,
) -> Iterator[Any]:
    subreddit = reddit.subreddit("+".join(subreddits))
    # pause_after=-1 yields None when caught up so the bot can service inbox polling.
    yield from subreddit.stream.comments(skip_existing=True, pause_after=-1)


def fetch_unread_mentions(reddit: praw.Reddit, limit: int = 25) -> list[Any]:
    items = list(reddit.inbox.unread(limit=limit))
    return [item for item in items if isinstance(item, praw.models.Comment)]


def safe_reply(item: Any, text: str, *, dry_run: bool, logger: Any) -> bool:
    permalink = getattr(item, "permalink", "")
    if dry_run:
        logger.info("Dry-run reply to %s:\n%s", permalink, text)
        return True
    try:
        item.reply(text)
        return True
    except praw.exceptions.RedditAPIException as exc:
        if any(getattr(error, "error_type", "") == "RATELIMIT" for error in exc.items):
            logger.warning("Reddit rate limit while replying to %s: %s", permalink, exc)
        else:
            logger.warning("Reddit API error while replying to %s: %s", permalink, exc)
        return False
    except (
        prawcore.exceptions.RequestException,
        prawcore.exceptions.ServerError,
        prawcore.exceptions.ResponseException,
    ) as exc:
        logger.warning("Reddit transient error while replying to %s: %s", permalink, exc)
        return False


def mark_read(item: Any) -> None:
    try:
        item.mark_read()
    except Exception:
        return


def has_own_reply(item: Any, bot_username: str) -> OwnReplyStatus:
    try:
        item.refresh()
        replies = getattr(item, "replies", []) or []
        for reply in replies:
            author = getattr(reply, "author", None)
            if author is not None and str(author).lower() == bot_username.lower():
                return "yes"
    except Exception:
        return "unknown"
    return "no"
