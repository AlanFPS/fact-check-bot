import { describe, expect, it } from "vitest";

import { getCachedOutcome, storeOutcome } from "../src/store/cache.js";
import { Verdict } from "../src/core/models.js";
import { FakeRedis } from "./helpers.js";

describe("cache store", () => {
  it("returns null for corrupt or incomplete cached outcomes", async () => {
    const redis = new FakeRedis();
    await redis.set("cache:bad-json", "not json");
    await redis.set("cache:bad-shape", JSON.stringify({ source: "llm" }));

    expect(await getCachedOutcome(redis, "cache:bad-json")).toBeNull();
    expect(await getCachedOutcome(redis, "cache:bad-shape")).toBeNull();
  });

  it("stores and reads valid outcomes", async () => {
    const redis = new FakeRedis();
    const outcome = {
      source: "llm" as const,
      claim: "Claim.",
      googleClaims: [],
      llmResult: {
        verdict: Verdict.TRUE,
        confidence: 1,
        reasoning: "Ok.",
        citedSources: []
      },
      evidence: []
    };

    await storeOutcome(redis, "cache:key", outcome, 60);

    expect(await getCachedOutcome(redis, "cache:key")).toEqual(outcome);
    expect(redis.expires.get("cache:key")).toBe(60);
  });
});
