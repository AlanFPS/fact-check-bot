"""Main bot loop and Reddit item handling."""

import time
from collections.abc import Callable
from typing import Any

import prawcore.exceptions

from factcheckbot.config import Settings
from factcheckbot.google_factcheck import GoogleFactCheckClient
from factcheckbot.llm import LlmClient, LlmError
from factcheckbot.logging_setup import get_logger
from factcheckbot.metrics import Metrics
from factcheckbot.models import TriggerContext
from factcheckbot.pipeline import Pipeline
from factcheckbot.rate_limit import RateLimiter
from factcheckbot.reddit_client import (
    fetch_unread_mentions,
    has_own_reply,
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
        metrics: Metrics | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.reddit = reddit
        self.seen = seen
        self.limiter = limiter
        self.metrics = metrics
        self._now = now
        self._last_metrics_log = now()
        self.pipeline = Pipeline(settings, searcher, llm, google, seen, metrics)
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
            self.reconcile_pending()
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
                    self._maybe_log_metrics()
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
        if self.metrics is not None:
            self.metrics.items_seen += 1
        item_id = item.fullname
        if self.seen.is_seen(item_id):
            logger.debug("Skipping seen item %s", item_id)
            return True

        body = getattr(item, "body", "") or ""
        trigger_body = strip_quoted_and_code(body)
        if not contains_trigger(trigger_body, self.settings.bot_trigger):
            self.seen.mark_seen_and_clear_pending(item_id)
            return True
        if self.metrics is not None:
            self.metrics.triggers_matched += 1

        author = str(item.author) if getattr(item, "author", None) else None
        if is_ignorable_author(author, self.settings.reddit_username, self.settings.ignore_bots):
            self.seen.mark_seen_and_clear_pending(item_id)
            return True

        allowed, reason = self.limiter.allow(author)
        if not allowed:
            if self.metrics is not None:
                self.metrics.rate_limited += 1
            log = logger.warning if reason == "global rate limit" else logger.info
            log("Skipping %s from %s: %s", item_id, author, reason)
            self.seen.mark_seen_and_clear_pending(item_id)
            return True

        if source == "comment_stream" and not self._allow_subreddit(item):
            logger.info("sub not allowlisted: %s", _item_subreddit_name(item) or "<unknown>")
            self.seen.mark_seen_and_clear_pending(item_id)
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
                if self._skip_existing_pending_reply(ctx, item):
                    return True
                reply = render_no_claim_reply(self.settings)
                self.seen.mark_pending(ctx.item_id)
                ok = safe_reply(item, reply, dry_run=self.settings.dry_run, logger=logger)
                if ok:
                    self.seen.mark_seen_and_clear_pending(ctx.item_id)
                    self.limiter.record(ctx.author or "")
                    self._record_reply_metric()
                return ok

            outcome = self.pipeline.run(claim)
        except LlmError as exc:
            if self.metrics is not None:
                self.metrics.llm_failures += 1
            logger.warning("LLM unavailable, leaving item for retry: %s", exc)
            return False

        if self._skip_existing_pending_reply(ctx, item):
            return True
        reply = render_outcome(outcome, self.settings)
        self.seen.mark_pending(ctx.item_id)
        ok = safe_reply(item, reply, dry_run=self.settings.dry_run, logger=logger)
        if ok:
            self.seen.mark_seen_and_clear_pending(ctx.item_id)
            self.limiter.record(ctx.author or "")
            self._record_reply_metric()
        else:
            logger.info("Reply failed for %s; item will be retried later", ctx.item_id)
        return ok

    def reconcile_pending(self) -> None:
        for item_id in self.seen.list_pending():
            try:
                item = self._load_reddit_item(item_id)
                if item is None:
                    continue
                status = has_own_reply(item, self.settings.reddit_username)
                if status == "yes":
                    self.seen.mark_seen_and_clear_pending(item_id)
                elif status == "no":
                    self.seen.clear_pending(item_id)
            except Exception:
                logger.warning("Failed to reconcile pending item %s", item_id)

    def _load_reddit_item(self, item_id: str) -> Any | None:
        try:
            if item_id.startswith("t1_") and hasattr(self.reddit, "comment"):
                return self.reddit.comment(id=item_id.removeprefix("t1_"))
        except Exception:
            return None
        return None

    def _allow_subreddit(self, item: Any) -> bool:
        if not self.settings.subreddit_allowlist:
            return True
        subreddit = _item_subreddit_name(item)
        return subreddit in self.settings.subreddit_allowlist

    def _skip_existing_pending_reply(self, ctx: TriggerContext, item: Any) -> bool:
        if ctx.source != "inbox_mention" or not self.seen.is_pending(ctx.item_id):
            return False
        if has_own_reply(item, self.settings.reddit_username) == "yes":
            self.seen.mark_seen_and_clear_pending(ctx.item_id)
            return True
        return False

    def _record_reply_metric(self) -> None:
        if self.metrics is None:
            return
        if self.settings.dry_run:
            self.metrics.dry_run_replies += 1
        else:
            self.metrics.replies_posted += 1

    def _maybe_log_metrics(self) -> None:
        if self.metrics is None:
            return
        now = self._now()
        if now - self._last_metrics_log < self.settings.metrics_log_interval_seconds:
            return
        self._last_metrics_log = now
        logger.info("metrics", extra=self.metrics.as_log_extra())

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


def _item_subreddit_name(item: Any) -> str:
    subreddit = getattr(item, "subreddit", "")
    display_name = getattr(subreddit, "display_name", None)
    return str(display_name or subreddit).lower()
