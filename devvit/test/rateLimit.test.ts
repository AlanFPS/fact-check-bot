import { describe, expect, it } from "vitest";

import { checkAndReserve } from "../src/store/rateLimit.js";
import { baseSettings, FakeRedis } from "./helpers.js";

describe("rate limit", () => {
  it("allows under limit and increments counters", async () => {
    const redis = new FakeRedis();
    const result = await checkAndReserve(redis, "alice", baseSettings, 0);
    expect(result).toEqual({ allowed: true, reason: "" });
    expect(await redis.get("rl:user:alice:0")).toBe("1");
    expect(await redis.get("rl:global:0")).toBe("1");
  });

  it("blocks per-user and global limits with increment-first reservation", async () => {
    const redis = new FakeRedis();
    const settings = { ...baseSettings, rateLimitPerUserPerHour: 1, rateLimitGlobalPerHour: 2 };
    expect((await checkAndReserve(redis, "alice", settings, 0)).allowed).toBe(true);
    expect(await checkAndReserve(redis, "alice", settings, 0)).toEqual({
      allowed: false,
      reason: "per-user rate limit"
    });
    expect(await redis.get("rl:user:alice:0")).toBe("2");
    expect((await checkAndReserve(redis, "bob", settings, 0)).allowed).toBe(true);
    expect(await checkAndReserve(redis, "carol", settings, 0)).toEqual({
      allowed: false,
      reason: "global rate limit"
    });
    expect(await redis.get("rl:global:0")).toBe("3");
  });

  it("uses hour buckets", async () => {
    const redis = new FakeRedis();
    const settings = { ...baseSettings, rateLimitPerUserPerHour: 1 };
    await checkAndReserve(redis, "alice", settings, 0);
    expect((await checkAndReserve(redis, "alice", settings, 3_600_000)).allowed).toBe(true);
  });
});
