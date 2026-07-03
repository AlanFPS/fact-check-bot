"""Main bot loop and Reddit item handling."""

import time
from typing import Any

import prawcore.exceptions

from factcheckbot.config import Settings
from factcheckbot.google_factcheck import GoogleFactCheckClient
from factcheckbot.llm import LlmClient, LlmError
from factcheckbot.logging_setup import get_logger
from factcheckbot.models import TriggerContext
from factcheckbot.pipeline import Pipeline
from factcheckbot.rate_limit import RateLimiter
from factcheckbot.reddit_client import (
    fetch_unread_mentions,
    iter_comment_stream,
    mark_read,
    safe_reply,
)
from factcheckbot.rendering import render_no_claim_reply, render_outcome
from factcheckbot.search import EvidenceSearcher
from factcheckbot.seen_store import SeenStore
from factcheckbot.triggers import (
    contains_trigger,
    extract_inline_query,
    is_ignorable_author,
    strip_quoted_and_code,
)

logger = get_logger(__name__)


class Bot:
    def __init__(
        self,
        settings: Settings,
        reddit: Any,
        searcher: EvidenceSearcher,
        llm: LlmClient,
        seen: SeenStore,
        limiter: RateLimiter,
        google: GoogleFactCheckClient | None = None,
    ) -> None:
        self.settings = settings
        self.reddit = reddit
        self.seen = seen
        self.limiter = limiter
        self.pipeline = Pipeline(settings, searcher, llm, google)
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        logger.info(
            "Starting bot: model=%s base_url=%s subreddits=%s dry_run=%s "
            "comment_stream=%s inbox=%s",
            self.settings.llm_model,
            self.settings.llm_base_url,
            ",".join(self.settings.monitored_subreddits),
            self.settings.dry_run,
            self.settings.enable_comment_stream,
            self.settings.enable_inbox_mentions,
        )
        try:
            comment_stream = None
            while not self._stop:
                try:
                    if self.settings.enable_comment_stream:
                        if comment_stream is None:
                            comment_stream = iter_comment_stream(
                                self.reddit,
                                self.settings.monitored_subreddits,
                            )
                        for comment in comment_stream:
                            if self._stop or comment is None:
                                break
                            self._handle_item(comment, "comment_stream")

                    if self.settings.enable_inbox_mentions:
                        for item in fetch_unread_mentions(self.reddit):
                            if self._stop:
                                break
                            should_mark_read = self._handle_item(item, "inbox_mention")
                            if should_mark_read:
                                mark_read(item)

                    time.sleep(self.settings.poll_sleep_seconds)
                except (
                    prawcore.exceptions.RequestException,
                    prawcore.exceptions.ServerError,
                    prawcore.exceptions.ResponseException,
                ) as exc:
                    comment_stream = None
                    logger.warning("Reddit transient error: %s", exc)
                    time.sleep(self.settings.poll_sleep_seconds)
                except Exception:
                    comment_stream = None
                    logger.exception("Unexpected bot loop error")
                    time.sleep(self.settings.poll_sleep_seconds)
        finally:
            self.seen.close()

    def _handle_item(self, item: Any, source: str) -> bool:
        item_id = item.fullname
        if self.seen.is_seen(item_id):
            logger.debug("Skipping seen item %s", item_id)
            return True

        body = getattr(item, "body", "") or ""
        trigger_body = strip_quoted_and_code(body)
        if not contains_trigger(trigger_body, self.settings.bot_trigger):
            self.seen.mark_seen(item_id)
            return True

        author = str(item.author) if getattr(item, "author", None) else None
        if is_ignorable_author(author, self.settings.reddit_username, self.settings.ignore_bots):
            self.seen.mark_seen(item_id)
            return True

        allowed, reason = self.limiter.allow(author)
        if not allowed:
            log = logger.warning if reason == "global rate limit" else logger.info
            log("Skipping %s from %s: %s", item_id, author, reason)
            self.seen.mark_seen(item_id)
            return True

        ctx = TriggerContext(
            item_id=item_id,
            author=author,
            inline_query=extract_inline_query(
                trigger_body,
                self.settings.bot_trigger,
                self.settings.max_claim_chars,
            ),
            permalink=getattr(item, "permalink", ""),
            source=source,  # type: ignore[arg-type]
        )
        return self._process(ctx, item)

    def _process(self, ctx: TriggerContext, item: Any) -> bool:
        try:
            claim = self.pipeline.resolve_claim(
                ctx,
                parent_text_getter=lambda: self._parent_text(item),
            )
            if claim == "":
                reply = render_no_claim_reply(self.settings)
                ok = safe_reply(item, reply, dry_run=self.settings.dry_run, logger=logger)
                if ok:
                    self.seen.mark_seen(ctx.item_id)
                    self.limiter.record(ctx.author or "")
                return ok

            outcome = self.pipeline.run(claim)
        except LlmError as exc:
            logger.warning("LLM unavailable, leaving item for retry: %s", exc)
            return False

        reply = render_outcome(outcome, self.settings)
        ok = safe_reply(item, reply, dry_run=self.settings.dry_run, logger=logger)
        if ok:
            self.seen.mark_seen(ctx.item_id)
            self.limiter.record(ctx.author or "")
        else:
            logger.info("Reply failed for %s; item will be retried later", ctx.item_id)
        return ok

    def _parent_text(self, item: Any) -> str | None:
        try:
            parent = item.parent()
        except Exception:
            return None
        body = getattr(parent, "body", None)
        if body:
            return str(body)
        title = getattr(parent, "title", "")
        selftext = getattr(parent, "selftext", "")
        text = f"{title}\n\n{selftext}".strip()
        return text or None
