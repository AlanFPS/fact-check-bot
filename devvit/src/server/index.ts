import { context, reddit, redis, scheduler, settings } from "@devvit/web/server";
import { Hono } from "hono";

import { GoogleFactCheckClient } from "../clients/google.js";
import { LlmClient, LlmError } from "../clients/llm.js";
import { SearchClient } from "../clients/search.js";
import { loadSettings } from "../core/config.js";
import type { PipelineOutcome, TriggerContext } from "../core/models.js";
import { Pipeline } from "../core/pipeline.js";
import { renderNoClaimReply, renderOutcome } from "../core/rendering.js";
import { containsTrigger, extractInlineQuery, isIgnorableAuthor, stripQuotedAndCode } from "../core/triggers.js";
import { cacheKey, getCachedOutcome, storeOutcome } from "../store/cache.js";
import { checkAndReserve } from "../store/rateLimit.js";
import type { RedisLike } from "../store/redis.js";
import { markSeenIfNew, SEEN_TTL } from "../store/seen.js";
import type { CommentSubmitPayload, ProcessFactcheckJobData } from "../types/devvit-payloads.js";

const app = new Hono();
const APP_ACCOUNT_NAME = "fact-check-bot";

app.post("/internal/triggers/on-comment-submit", async (c) => {
  try {
    const input = (await c.req.json()) as CommentSubmitPayload;
    const commentId = input.comment?.id;
    if (!commentId) {
      return c.json({ status: "ignored" });
    }
    const cfg = await loadSettings((name) => settings.get(name));
    const rawBody = input.comment?.body ?? "";
    const stripped = stripQuotedAndCode(rawBody);
    if (!containsTrigger(stripped, cfg.botTrigger)) {
      return c.json({ status: "ok" });
    }
    const authorName = input.author?.name ?? input.comment?.author ?? null;
    const selfName = await getSelfUsername();
    if (isIgnorableAuthor(authorName, selfName, cfg.ignoreBots)) {
      return c.json({ status: "ok" });
    }
    const redisLike = redisAdapter();
    if (!(await markSeenIfNew(redisLike, commentId, SEEN_TTL))) {
      return c.json({ status: "ok" });
    }
    const rl = await checkAndReserve(redisLike, authorName, cfg, Date.now());
    if (!rl.allowed) {
      console.log("rate limited", rl.reason, commentId);
      return c.json({ status: "ok" });
    }
    const jobData: ProcessFactcheckJobData = {
      commentId,
      authorName,
      inlineBody: stripped
    };
    if (input.comment?.parentId) {
      jobData.parentId = input.comment.parentId;
    }
    if (input.comment?.postId) {
      jobData.postId = input.comment.postId;
    }
    if (input.comment?.permalink) {
      jobData.permalink = input.comment.permalink;
    }
    await scheduler.runJob({
      name: "process-factcheck",
      data: jobData as unknown as Record<string, string | null>,
      runAt: new Date()
    });
    return c.json({ status: "ok" });
  } catch (error) {
    console.warn("comment trigger failed", error instanceof Error ? error.name : "Error");
    return c.json({ status: "ok" });
  }
});

app.post("/internal/scheduler/process-factcheck", async (c) => {
  const request = (await c.req.json()) as { data?: ProcessFactcheckJobData } | ProcessFactcheckJobData;
  const data = "data" in request && request.data ? request.data : (request as ProcessFactcheckJobData);
  const cfg = await loadSettings((name) => settings.get(name));
  const llm = new LlmClient(cfg);
  const google = cfg.googleFactCheckApiKey ? new GoogleFactCheckClient(cfg) : null;
  const search = cfg.searchApiKey ? new SearchClient(cfg) : null;
  const redisLike = redisAdapter();
  const cache = cfg.enableVerdictCache
    ? {
        key: cacheKey,
        get: (key: string) => getCachedOutcome(redisLike, key),
        put: (key: string, outcome: PipelineOutcome) =>
          storeOutcome(redisLike, key, outcome, cfg.cacheTtlSeconds)
      }
    : null;
  const pipeline = new Pipeline({ settings: cfg, llm, google, search, cache });
  const ctx: TriggerContext = {
    itemId: data.commentId,
    author: data.authorName,
    inlineQuery: extractInlineQuery(data.inlineBody, cfg.botTrigger, cfg.maxClaimChars),
    permalink: data.permalink ?? "",
    source: "comment_submit"
  };
  try {
    const claim = await pipeline.resolveClaim(ctx, () => getParentText(data));
    const text =
      claim === ""
        ? renderNoClaimReply(cfg)
        : renderOutcome(await pipeline.run(claim), cfg);
    if (cfg.dryRun) {
      console.log("[dry-run] would reply to", data.commentId, "\n", text);
    } else {
      await reddit.submitComment({ id: data.commentId as `t1_${string}`, text, runAs: "APP" });
    }
  } catch (error) {
    if (error instanceof LlmError) {
      console.warn("LLM unavailable; skipping reply", data.commentId);
    } else {
      console.warn("process-factcheck failed", error instanceof Error ? error.name : "Error");
    }
  }
  return c.json({ status: "ok" });
});

async function getParentText(data: ProcessFactcheckJobData): Promise<string | null> {
  try {
    if (data.parentId?.startsWith("t1_")) {
      const comment = await reddit.getCommentById(data.parentId as `t1_${string}`);
      return typeof comment.body === "string" ? comment.body : null;
    }
    const postId = data.parentId?.startsWith("t3_") ? data.parentId : data.postId;
    if (postId) {
      const post = await reddit.getPostById(postId as `t3_${string}`);
      const body = typeof post.body === "string" ? post.body : "";
      const title = typeof post.title === "string" ? post.title : "";
      return `${title}\n\n${body}`.trim() || null;
    }
  } catch {
    return null;
  }
  return null;
}

function redisAdapter(): RedisLike {
  return {
    get: async (key) => (await redis.get(key)) ?? null,
    set: async (key, value, opts) => {
      try {
        return await redis.set(key, value, opts);
      } catch {
        if (opts?.nx && (await redis.get(key)) !== undefined) {
          return null;
        }
        return null;
      }
    },
    incrBy: (key, n) => redis.incrBy(key, n),
    expire: (key, seconds) => redis.expire(key, seconds)
  };
}

async function getSelfUsername(): Promise<string> {
  try {
    const appUser = await reddit.getAppUser();
    return appUser?.username ?? context.appName ?? APP_ACCOUNT_NAME;
  } catch {
    return context.appName ?? APP_ACCOUNT_NAME;
  }
}

export default app;
