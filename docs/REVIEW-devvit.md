# Devvit Review

## Overall Assessment

I would not enable live posting on a real subreddit until the self-author filter is made runtime-derived and covered by a server-level test. The current code probably skips the app's own comments when the app account username is exactly `fact-check-bot`, and the default `ignoreBots=true` gives a second layer because that name ends in `bot`. That is still too brittle for the highest-risk live-bot path.

With `dryRun=true`, this is safe to playtest. For an educational project it is close, but not shippable with live replies until F-001 is fixed and the Hono trigger/scheduler paths have tests.

Behavior parity is generally strong in the pure modules: prompts, verdict schema, tolerant JSON parsing, Google mapping, rendering, trigger stripping, Redis TTLs, and fallback behavior are mostly faithful. The main gaps are in the Devvit edge wiring, rate-limit atomicity, cache validation, and test coverage around live posting.

## Findings

| ID | Severity | File:line | Issue | Suggested fix |
|---|---|---:|---|---|
| F-001 | HIGH | `devvit/src/server/index.ts:19` | Self-author filtering depends on a hard-coded app account name and is not tested through the real trigger handler. If the runtime app account username ever differs from this string, especially with `ignoreBots=false`, an app-authored comment containing a trigger outside quote/code could be scheduled and replied to. | Derive the app account at runtime with `reddit.getAppUser()` or `context.appName/appSlug`, compare against both `input.author?.name` and `input.comment?.author`, and add Hono handler tests for app-authored comments, app-authored comments with `ignoreBots=false`, duplicate delivery, and dry-run posting. |
| F-002 | MEDIUM | `devvit/src/server/index.ts:34` | Author extraction ignores `comment.author`, even though Devvit's `CommentV2` type includes it. If the top-level `author` object is absent but `comment.author` is present, the app treats the author as null and silently skips legitimate trigger comments. | Use `input.author?.name ?? input.comment?.author ?? null`; update `CommentSubmitPayload` to match `OnCommentSubmitRequest` more closely. |
| F-003 | MEDIUM | `devvit/src/store/rateLimit.ts:23` | Rate-limit reservation is a read-then-increment sequence. Concurrent trigger events can all observe counts below the limit and then all increment, allowing bursts past both per-user and global limits. | Use Redis transactions with `watch`/`multi`/`exec`, or an atomic counter strategy that increments first and rolls back/blocks when over limit. |
| F-004 | MEDIUM | `devvit/src/store/cache.ts:23` | Cache validation only checks `source`. A corrupt value like `{"source":"llm"}` is accepted as a `PipelineOutcome`, then `renderOutcome` throws and the job drops the reply. | Validate the full outcome shape before returning cached data, including `claim`, `googleClaims`, `llmResult`, and `evidence`, or parse through a stricter schema. |
| F-005 | MEDIUM | `devvit/src/core/config.ts:34` | `llmBaseUrl` is moderator-configurable but not validated as HTTPS or restricted to the allowlisted domain. A bad value fails at runtime and can drift from `devvit.json`'s reviewed domains. | Validate `llmBaseUrl` in `loadSettings`, requiring HTTPS and an allowlisted hostname, or replace free-form URL with a provider selector. |
| F-006 | MEDIUM | `devvit/test/triggers.test.ts:43` | Tests cover pure helpers but not the Hono trigger/scheduler wiring where self-skip, dedupe, rate-limit reservation, scheduler enqueue, `dryRun`, and `submitComment` actually happen. | Add server tests with mocked `@devvit/web/server` exports and exercise `/internal/triggers/on-comment-submit` plus `/internal/scheduler/process-factcheck`. |
| F-007 | LOW | `devvit/src/server/index.ts:140` | The fallback path for Redis clients without `set(..., { nx: true })` emulates NX with `get` then `set`, which is non-atomic and can double-enqueue under re-delivery races. Current `@devvit/redis` supports `nx`, so this is mostly a compatibility hazard. | Prefer failing closed if NX is unavailable, or use `watch`/transaction in the fallback. |
| F-008 | LOW | `devvit/src/clients/google.ts:35` | Google and Tavily timeout timers are only cleared after `fetch` resolves. If `fetch` rejects before that point, the timer is left pending until it fires. | Move `clearTimeout(timeout)` into a `finally` block in both clients. |

## Critical/High Details

### F-001, Self-author filter is hard-coded and untested

Snippet:

```ts
const APP_ACCOUNT_NAME = "fact-check-bot";

// ...

const authorName = input.author?.name ?? null;
if (isIgnorableAuthor(authorName, APP_ACCOUNT_NAME, cfg.ignoreBots)) {
  return c.json({ status: "ok" });
}
```

Why this matters: every bot reply is itself a `CommentSubmit` event. The current reply footer puts the trigger token inside inline code, and the parser strips inline code before matching, so the normal generated reply probably will not self-trigger. That helps, but it is not a sufficient loop-safety guarantee. A future template change, Google table cell, source title, or model reasoning could include `!factcheck` outside code/quote. At that point the only hard stop is the author filter.

The installed `@devvit/web/server` package re-exports `context` through `@devvit/server`, and `reddit.getAppUser()` derives the app user from `context.appName`. The code should use that runtime value instead of a literal. It should also read `input.comment?.author`, because Devvit's `CommentV2` has `author: string`.

Concrete fix:

```ts
const appUser = await reddit.getAppUser();
const selfName = appUser?.username ?? context.appName;
const authorName = input.author?.name ?? input.comment?.author ?? null;

if (isIgnorableAuthor(authorName, selfName, cfg.ignoreBots)) {
  return c.json({ status: "ok" });
}
```

Then add handler tests that submit an app-authored comment containing `!factcheck` outside code/quote and assert there is no `markSeenIfNew`, no `checkAndReserve`, and no `scheduler.runJob`, with both `ignoreBots=true` and `ignoreBots=false`.

## Run Summary

All required commands were run from `devvit/`.

| Command | Result |
|---|---|
| `npm run typecheck` | Passed |
| `npm run build` | Passed, produced `dist/server/index.cjs` |
| `npm test` | Passed, 9 files and 31 tests |

## Explicit Safety Answers

| Question | Answer |
|---|---|
| Can the bot reply to its own comments or infinite-loop? | No for the current `fact-check-bot` app slug under the current reply templates, but the guard is not airtight. If the runtime app account name differs from the hard-coded string and a bot-authored comment contains the trigger outside code/quote, it can self-schedule. |
| Is the self-author filter correct given `context` is not exported? | No as implemented. The installed package does export `context` via `@devvit/server`, and `reddit.getAppUser()` is also available. A hard-coded slug is not the right safety boundary. |
| Can any API key leak into logs or replies? | No obvious leak found. The clients log status codes or error names only, not error messages or request URLs. Dry-run logs only generated reply text. |
| Does `dryRun` reliably prevent posting? | Yes in the scheduler path: `reddit.submitComment` is only called in the `else` branch when `cfg.dryRun` is false. |
| Is `devvit.json` valid for current Devvit Web? | Yes based on the saved Devvit Web docs and installed package shape: server entry, Reddit/Redis/HTTP permissions, CommentSubmit trigger, scheduler task, and secret settings are consistent. I still recommend a CLI `devvit playtest` or upload validation before real installation because local `npm run build` does not validate Reddit's config schema. |

## Test Coverage Notes

The existing tests are useful for pure logic: triggers, JSON parsing, rendering, Google mapping, LLM retry/fallback, Tavily mapping, Redis seen, rate limits, and pipeline tiering. They are not shallow in those areas.

The missing coverage is exactly where live-bot risk concentrates:

- No Hono trigger test proves app-authored comments are skipped.
- No test proves duplicate CommentSubmit delivery does not enqueue twice through the actual endpoint.
- No test proves `dryRun=true` prevents `reddit.submitComment`.
- No test proves scheduler payload envelope compatibility with Devvit's `TaskRequest`.
- No test covers corrupt cache values flowing through the full render path.

