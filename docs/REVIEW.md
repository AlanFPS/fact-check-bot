# Review

Overall, this is close for a dry-run educational project, but I would not run it unattended yet. The pure pipeline pieces are readable and mostly covered, but the live Reddit loop has two operational bugs that can drop or lose triggers, and malformed LLM JSON can still crash a processing cycle.

## Findings

| ID | Severity | File:line | Issue | Suggested fix |
|---|---|---:|---|---|
| F-001 | HIGH | `src/factcheckbot/bot.py:60` / `src/factcheckbot/reddit_client.py:32` | The comment stream is recreated on every outer loop with `skip_existing=True` and `pause_after=-1`. PRAW yields `None` after the first response, the bot breaks, then recreates a new stream that skips the next first response again. In practice, comment-stream triggers can be skipped forever. | Keep one stream generator alive across loop iterations, or track `continue_after_id` and only use `skip_existing=True` once at startup. |
| F-002 | HIGH | `src/factcheckbot/bot.py:72` | Inbox items are marked read unconditionally after `_handle_item`, even when `_process` deliberately leaves them unseen after LLM downtime or Reddit reply failure. Because polling uses `reddit.inbox.unread`, those failed mentions will not be retried. | Make `_handle_item` return a status and call `mark_read` only after success or an intentional terminal skip. Do not mark read when the item remains unprocessed for retry. |
| F-003 | HIGH | `src/factcheckbot/models.py:33` / `src/factcheckbot/rendering.py:35` | Python's `json.loads` accepts `NaN`, Pydantic accepts it as a float, and `round(result.confidence * 100)` raises `ValueError`. A malformed LLM response that parses as JSON can crash the loop and retry forever. | Reject non-finite floats during JSON parse or model validation, then use the existing LLM retry/default verdict path. |
| F-004 | MEDIUM | `src/factcheckbot/prompts.py:31` | Claim and evidence are interpolated directly into the user prompt with weak delimiters and no explicit untrusted-input instruction. A claim containing prompt-like text can compete with the verdict rules. | Harden the system prompt and wrap claim/evidence as explicitly untrusted data, preferably serialized with `json.dumps` instead of ad hoc quote blocks. |
| F-005 | MEDIUM | `src/factcheckbot/triggers.py:8` | Trigger detection is a raw case-insensitive substring search, so quoted text and fenced code blocks containing `!factcheck` can trigger the bot. That can make the bot respond to someone quoting another trigger or posting code. | Strip or ignore Markdown blockquotes and fenced/indented code before trigger detection, and add tests for quoted/code-block triggers. |
| F-006 | MEDIUM | `src/factcheckbot/search.py:16` | `SEARCH_TIMEOUT_SECONDS` is documented but not used. `DDGS()` defaults its own timeout, so the configured timeout does not control the search step. | Pass `timeout=settings.search_timeout_seconds` to the `DDGS` factory or document that the setting is unused and remove it. |
| F-007 | MEDIUM | `src/factcheckbot/bot.py:147` | There is no idempotency guard for the crash window between `item.reply(text)` succeeding and `seen.mark_seen(...)` committing. A process crash in that gap can double-reply on restart. | Before replying, check recent own replies on the item, or persist a pending/replied state before calling Reddit and reconcile it after success. |
| F-008 | LOW | `src/factcheckbot/reddit_client.py:35` | `fetch_unread_mentions` fetches all unread inbox items with a `body`, not just username mentions. It can process PMs or comment replies that happen to contain the trigger. | Use `reddit.inbox.mentions(...)` or filter unread items to PRAW mention/comment types that are actually username mentions. |
| F-009 | LOW | `src/factcheckbot/rendering.py:69` | Source titles and URLs from `ddgs` are inserted into Markdown without escaping. Bad result text can break formatting or create misleading links, though reply length is still capped. | Escape Markdown-sensitive title characters and reject non-http(s) URLs before rendering. |

## High-Severity Details

### F-001: Comment stream can skip every comment

Problematic snippets:

```python
while not self._stop:
    try:
        if self.settings.enable_comment_stream:
            for comment in iter_comment_stream(
                self.reddit,
                self.settings.monitored_subreddits,
            ):
                if self._stop or comment is None:
                    break
```

```python
def iter_comment_stream(
    reddit: praw.Reddit,
    subreddits: list[str],
    pause_after: int | None = None,
) -> Iterator[Any]:
    subreddit = reddit.subreddit("+".join(subreddits))
    # pause_after=-1 yields None when caught up so the bot can service inbox polling.
    yield from subreddit.stream.comments(skip_existing=True, pause_after=-1)
```

PRAW 8 documents negative `pause_after` as yielding `None` after items from a single response have been yielded. Since the bot breaks on that `None` and creates a new generator next loop, `skip_existing=True` applies to every poll, not just startup.

Concrete fix:

```diff
- while not self._stop:
+ comment_stream = None
+ while not self._stop:
      try:
          if self.settings.enable_comment_stream:
-             for comment in iter_comment_stream(
-                 self.reddit,
-                 self.settings.monitored_subreddits,
-             ):
+             if comment_stream is None:
+                 comment_stream = iter_comment_stream(
+                     self.reddit,
+                     self.settings.monitored_subreddits,
+                 )
+             for comment in comment_stream:
                  if self._stop or comment is None:
                      break
                  self._handle_item(comment, "comment_stream")
```

If the stream raises, reset `comment_stream = None` in the exception handler so a broken generator can be rebuilt.

### F-002: Inbox retry semantics are broken

Problematic snippet:

```python
if self.settings.enable_inbox_mentions:
    for item in fetch_unread_mentions(self.reddit):
        if self._stop:
            break
        self._handle_item(item, "inbox_mention")
        mark_read(item)
```

`_process` intentionally does not mark seen on `LlmError` or failed `safe_reply`, but `mark_read(item)` still runs after `_handle_item` returns. The next inbox poll uses `reddit.inbox.unread(...)`, so the item disappears from the retry source while remaining absent from SQLite.

Concrete fix:

```diff
- self._handle_item(item, "inbox_mention")
- mark_read(item)
+ should_mark_read = self._handle_item(item, "inbox_mention")
+ if should_mark_read:
+     mark_read(item)
```

Then make `_handle_item` return `True` for already-seen, no-trigger, ignored-author, rate-limited, and successfully processed items, and `False` when LLM/reply failure leaves the item unprocessed for retry.

### F-003: `NaN` confidence can crash rendering

Problematic snippets:

```python
@field_validator("confidence")
@classmethod
def clamp_confidence(cls, value: float) -> float:
    return min(max(value, 0.0), 1.0)
```

```python
confidence = round(result.confidence * 100)
```

`json.loads('{"confidence": NaN, ...}')` returns `float("nan")`; Pydantic accepts it; `min(max(nan, 0.0), 1.0)` stays `nan`; `round(nan)` raises `ValueError: cannot convert float NaN to integer`.

Concrete fix:

```diff
+ import math
+
  @field_validator("confidence")
  @classmethod
  def clamp_confidence(cls, value: float) -> float:
+     if not math.isfinite(value):
+         raise ValueError("confidence must be finite")
      return min(max(value, 0.0), 1.0)
```

Also consider strict JSON parsing:

```python
json.loads(candidate, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
```

and catch that validation failure in `LlmClient.fact_check` so the retry/default path handles it.

## Test Run

Command run in the provided venv:

```text
source .venv/bin/activate && pytest
```

Result:

```text
...............................                                          [100%]
31 passed in 0.26s
```

Additional compatibility check:

```text
python -m pip check
No broken requirements found.
```

The tests are meaningful for config parsing, trigger helpers, search mapping, JSON extraction, rendering limits, SQLite persistence, rate limiting, and pure pipeline wiring. Important untested paths remain: persistent comment-stream behavior across `pause_after=-1`, inbox `mark_read` retry behavior, Reddit reply failure paths, NaN/non-finite LLM output, quoted/code-block triggers, prompt injection attempts, and crash-window idempotency after a successful reply.

## Python 3.14

The suite ran under Python 3.14.6, imports succeeded, and `pip check` reported no broken requirements. Installed dependency metadata is compatible with 3.14 for the relevant packages: `praw 8.0.2` and `prawcore 4.0.0` require `>=3.10`, `ddgs 9.14.4` requires `>=3.10` and advertises Python 3.14, `openai 1.109.1` requires `>=3.8`, `pydantic 2.13.4` requires `>=3.9`, and `pydantic-settings 2.14.2` requires `>=3.10`.

I do not see a code or dependency reason for `<3.14`. Relax it to `>=3.11,<3.15` or remove the upper bound if CI includes Python 3.14. Keep an upper bound only if the project will not test new Python releases promptly.
