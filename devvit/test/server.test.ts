import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const redisValues = new Map<string, string>();
  return {
    redisValues,
    reddit: {
      getAppUser: vi.fn(),
      submitComment: vi.fn(),
      getCommentById: vi.fn(),
      getPostById: vi.fn()
    },
    redis: {
      get: vi.fn(async (key: string) => redisValues.get(key)),
      set: vi.fn(async (key: string, value: string, opts?: { nx?: boolean }) => {
        if (opts?.nx && redisValues.has(key)) {
          return null;
        }
        redisValues.set(key, value);
        return "OK";
      }),
      incrBy: vi.fn(async (key: string, value: number) => {
        const next = Number(redisValues.get(key) ?? "0") + value;
        redisValues.set(key, String(next));
        return next;
      }),
      expire: vi.fn(async () => undefined)
    },
    scheduler: {
      runJob: vi.fn(async () => "job-id")
    },
    settings: {
      get: vi.fn()
    },
    context: {
      appName: "fallback-app"
    }
  };
});

vi.mock("@devvit/web/server", () => mocks);

const { default: app } = await import("../src/server/index.js");

function setSettings(values: Record<string, unknown> = {}): void {
  mocks.settings.get.mockImplementation(async (name: string) => values[name]);
}

function llmFetch(verdict = "TRUE"): typeof fetch {
  return vi.fn(async () =>
    new Response(
      JSON.stringify({
        choices: [
          {
            message: {
              content: JSON.stringify({
                verdict,
                confidence: 0.9,
                reasoning: "The model returned a verdict.",
                cited_sources: []
              })
            }
          }
        ]
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    )
  ) as unknown as typeof fetch;
}

async function postTrigger(payload: unknown): Promise<Response> {
  return app.request("/internal/triggers/on-comment-submit", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" }
  });
}

async function postScheduler(data: unknown): Promise<Response> {
  return app.request("/internal/scheduler/process-factcheck", {
    method: "POST",
    body: JSON.stringify({ data }),
    headers: { "Content-Type": "application/json" }
  });
}

beforeEach(() => {
  mocks.redisValues.clear();
  vi.clearAllMocks();
  mocks.reddit.getAppUser.mockResolvedValue({ username: "appuser" });
  setSettings({ llmApiKey: "llm-key" });
  vi.stubGlobal("fetch", llmFetch());
});

describe("server trigger endpoint", () => {
  it.each([true, false])(
    "skips app-authored comments before dedupe when ignoreBots=%s",
    async (ignoreBots) => {
      setSettings({ llmApiKey: "llm-key", ignoreBots });

      await postTrigger({
        comment: {
          id: "t1_self",
          body: "!factcheck loop risk",
          author: "appuser"
        }
      });

      expect(mocks.reddit.getAppUser).toHaveBeenCalled();
      expect(mocks.redis.set).not.toHaveBeenCalled();
      expect(mocks.redis.incrBy).not.toHaveBeenCalled();
      expect(mocks.scheduler.runJob).not.toHaveBeenCalled();
    }
  );

  it("uses comment.author when top-level author is absent and enqueues normal triggers", async () => {
    await postTrigger({
      comment: {
        id: "t1_normal",
        body: "!factcheck the earth is flat",
        author: "alice",
        parentId: "t3_post",
        postId: "t3_post"
      }
    });

    expect(mocks.scheduler.runJob).toHaveBeenCalledTimes(1);
    const calls = (
      mocks.scheduler.runJob as unknown as {
        mock: { calls: Array<[{ data: { authorName?: string | null } }]> };
      }
    ).mock.calls;
    const job = calls[0]?.[0];
    expect(job?.data.authorName).toBe("alice");
  });

  it("does not enqueue duplicate deliveries", async () => {
    const payload = {
      author: { name: "alice" },
      comment: { id: "t1_dupe", body: "!factcheck claim" }
    };

    await postTrigger(payload);
    await postTrigger(payload);

    expect(mocks.scheduler.runJob).toHaveBeenCalledTimes(1);
  });
});

describe("server scheduler endpoint", () => {
  it("does not submit comments in dry-run mode", async () => {
    setSettings({ llmApiKey: "llm-key", dryRun: true });

    await postScheduler({
      commentId: "t1_job",
      authorName: "alice",
      inlineBody: "!factcheck claim"
    });

    expect(mocks.reddit.submitComment).not.toHaveBeenCalled();
  });

  it("submits comments when dryRun=false", async () => {
    setSettings({ llmApiKey: "llm-key", dryRun: false });

    await postScheduler({
      commentId: "t1_job",
      authorName: "alice",
      inlineBody: "!factcheck claim"
    });

    expect(mocks.reddit.submitComment).toHaveBeenCalledTimes(1);
    expect(mocks.reddit.submitComment.mock.calls[0]?.[0].text).toContain("**Fact check:");
  });

  it("recomputes through corrupt cache and still renders a reply", async () => {
    setSettings({ llmApiKey: "llm-key", dryRun: false, enableVerdictCache: true });
    mocks.redis.get.mockImplementation(async (key: string) => {
      if (key.startsWith("cache:")) {
        return JSON.stringify({ source: "llm" });
      }
      return mocks.redisValues.get(key);
    });

    await postScheduler({
      commentId: "t1_cached",
      authorName: "alice",
      inlineBody: "!factcheck claim"
    });

    expect(mocks.reddit.submitComment).toHaveBeenCalledTimes(1);
    expect(mocks.reddit.submitComment.mock.calls[0]?.[0].text).toContain("**Fact check:");
  });
});
