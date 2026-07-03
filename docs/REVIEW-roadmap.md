# Roadmap Feature Review

Overall, I would not call this batch behavior-preserving yet. It is probably close enough for an educational dry-run project after the high-severity items are fixed, but the current defaults are not byte-for-byte equivalent to the reviewed baseline: pending writes, startup reconciliation, and periodic metrics logging are active even when cache, full-text evidence, and allowlist are left at their defaults.

The highest-risk area is R-1. The `seen` + `pending` atomic clear is implemented correctly for the happy path, but the pending marker can be discarded when Reddit is temporarily unavailable, and pending rows are not consulted before retrying an already-pending item. That means the new idempotency layer does not reliably close the double-reply crash window.

## Findings

| ID | Severity | File:line | Issue | Suggested fix |
|---|---|---:|---|---|
| RD-001 | HIGH | `src/factcheckbot/bot.py:74`, `src/factcheckbot/bot.py:168`, `src/factcheckbot/bot.py:232`, `src/factcheckbot/__main__.py:28` | Default runtime behavior is not byte-for-byte equivalent to the pre-roadmap reviewed bot. With all new env vars unset, the bot still creates metrics, runs `reconcile_pending()` at startup, writes `pending` rows before replies, and emits periodic metrics logs. | Decide whether R-1/R-4 are intentionally always-on. If strict behavior preservation is required, gate metrics logging and pending reconciliation/writes behind explicit settings, or update the merge criteria to say only Reddit reply behavior is preserved. |
| RD-002 | HIGH | `src/factcheckbot/bot.py:196`, `src/factcheckbot/reddit_client.py:70` | Pending reconciliation can discard the only crash-safety marker when Reddit cannot be queried, then the item remains unseen and can be replied to again later. The running bot also does not check an existing pending row before retrying an unread inbox item after an ambiguous failed reply. | Make own-reply detection tri-state: `yes`, `no`, `unknown`. Keep the pending row on `unknown`, retry reconciliation later, and before processing an already-pending item, check for an existing own reply before calling `safe_reply` again. |
| RD-003 | HIGH | `src/factcheckbot/pipeline.py:42` | The verdict cache key always uses `tier_scope="any"`, so a cached LLM result can be served after the Google tier is enabled, or a cached Google result can be served after the key is removed. This is the stale-tier hazard the spec called out. | Include the effective tier configuration in the key, at minimum `llm-only` vs `google-first`. If caching final outcomes, also include Google language/max-claims and any other settings that change the outcome shape. |
| RD-004 | MEDIUM | `src/factcheckbot/bot.py:225` | Metrics count dry-run replies as `replies_posted` and `dry_run_replies`, so the posted counter is misleading when the default `DRY_RUN=true` is used. The default metrics clock is `time.time`, not monotonic. | Increment `replies_posted` only for real Reddit posts, or rename it to `reply_successes`. Use `time.monotonic` for interval scheduling while keeping an injectable clock for tests. |
| RD-005 | MEDIUM | `src/factcheckbot/bot.py:183` | The subreddit allowlist check runs after `pipeline.run()`. A denied comment-stream trigger still performs Google/search/LLM work before being skipped, which is surprising for an opt-in safety gate. | Move the allowlist decision before expensive pipeline work, after trigger/author/rate-limit checks and before claim resolution or verdict generation. Inbox mentions can keep bypassing the check. |
| RD-006 | LOW | `src/factcheckbot/search.py:88` | Full-text extraction relies on the DDGS constructor timeout but does not enforce a per-call timeout around `extract()`. If `extract()` ignores the constructor timeout or stalls, the main loop can still hang while the feature is enabled. | Prefer an API-level timeout if `DDGS.extract` supports it, or isolate extraction behind a bounded worker/future. Keep returning snippets on timeout. |

## High-Severity Details

### RD-001: Defaults are not byte-for-byte equivalent

Relevant snippets:

```python
try:
    self.reconcile_pending()
    comment_stream = None
    while not self._stop:
```

```python
self.seen.mark_pending(ctx.item_id)
ok = safe_reply(item, reply, dry_run=self.settings.dry_run, logger=logger)
```

```python
def _maybe_log_metrics(self) -> None:
    if self.metrics is None:
        return
```

```python
metrics = Metrics()
searcher = EvidenceSearcher(settings, metrics=metrics)
```

Concrete fix: either put the new persistence and metrics behavior behind explicit flags, or state clearly that "behavior preservation" means reply decisions only. As written, the default process does extra SQLite writes, runs reconciliation, and logs metrics.

### RD-002: Pending reconciliation is not crash-safe enough

Relevant snippets:

```python
def reconcile_pending(self) -> None:
    for item_id in self.seen.list_pending():
        try:
            item = self._load_reddit_item(item_id)
            if item is not None and has_own_reply(item, self.settings.reddit_username):
                self.seen.mark_seen_and_clear_pending(item_id)
            else:
                self.seen.clear_pending(item_id)
        except Exception:
            logger.warning("Failed to reconcile pending item %s", item_id)
```

```python
def has_own_reply(item: Any, bot_username: str) -> bool:
    try:
        item.refresh()
        replies = getattr(item, "replies", []) or []
        for reply in replies:
            author = getattr(reply, "author", None)
            if author is not None and str(author).lower() == bot_username.lower():
                return True
    except Exception:
        return False
    return False
```

If `item.refresh()` fails because Reddit is unavailable, `has_own_reply()` returns `False`, and `reconcile_pending()` clears the pending row. That converts "maybe already replied" into "safe to retry" without evidence. `_load_reddit_item()` also returns `None` on load failures, which takes the same clear-pending path.

Concrete fix: do not collapse "no own reply" and "could not check" into the same boolean. Keep pending rows when the check is unknown. Add an `is_pending()` or `mark_pending()` return value and have `_handle_item()` reconcile an already-pending item before retrying it, especially for inbox mentions that remain unread after a failed reply.

### RD-003: Cache key ignores the active tier

Relevant snippet:

```python
def run(self, claim: str) -> PipelineOutcome:
    cache_key = _cache_key(normalize_claim(claim, self.settings.max_claim_chars), "any")
    if self.settings.enable_verdict_cache and self.cache_store is not None:
```

This makes cache entries portable across materially different tier setups. A user can run with cache enabled and no Google key, cache an LLM verdict, add a Google key later, and keep receiving the stale LLM outcome until TTL expiry. The reverse is also possible.

Concrete fix: compute the key from the normalized claim plus an effective tier scope such as `llm-only` or `google-first:<language>:<max_claims>`. If full-text evidence changes the LLM prompt, include that feature state too.

## Pytest Run

Command:

```text
source .venv/bin/activate && pytest
```

Result:

```text
74 passed in 0.32s
```

Additional local CI checks:

```text
source .venv/bin/activate && ruff check . && ruff format --check .
All checks passed!
30 files already formatted
```

The new tests are useful for the happy paths: disabled full-text no-op, cache hit and TTL expiry, pending helper atomicity, startup reconcile with fake Reddit, allowlist allow/deny, inbox mark-read retry behavior, and metrics increments. Important missing tests remain: transient Reddit failure during pending reconciliation, same-process retry of an already-pending inbox item, dry-run crash after `mark_pending`, cache tier changes between Google and LLM modes, corrupt cache payload recompute, extraction returning list/garbage, and metrics logging handler failures.

## Explicit Answers

- With all new flags at defaults, is behavior equivalent to pre-roadmap master? No. Cache and full-text are off and an empty allowlist is a no-op, but pending/reconcile and metrics are active by default.
- Can R-1 double-reply or crash startup? It should not crash startup because reconciliation is broadly guarded, but it can still double-reply after a pending row is cleared on an unknown Reddit check or when an already-pending inbox item is retried without an own-reply check.
- Does `DRY_RUN` correctly avoid leaving orphan pending rows? Mostly in the normal path, because `safe_reply(..., dry_run=True)` returns true and the row is cleared. No under crash semantics: a crash after `mark_pending()` can leave a dry-run-only pending row that later triggers live reconciliation work.
- Can a cache hit serve a stale-tier verdict? Yes. The key uses `any` instead of the active Google-vs-LLM tier scope.
- Can `extract()`/metrics/reconcile throw into and kill the main loop? `extract()` exceptions are swallowed when full-text is enabled, and reconciliation is guarded. Metrics logging is inside the bot loop's broad exception handler, so it can disrupt a cycle but should not permanently kill the loop. A true `extract()` hang is still possible if `DDGS.extract()` does not honor the constructor timeout.
