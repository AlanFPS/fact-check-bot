import { describe, expect, it } from "vitest";

import { markSeenIfNew, SEEN_TTL, seenKey } from "../src/store/seen.js";
import { FakeRedis } from "./helpers.js";

describe("seen store", () => {
  it("marks comments once and expires the key", async () => {
    const redis = new FakeRedis();
    expect(await markSeenIfNew(redis, "t1_a")).toBe(true);
    expect(await markSeenIfNew(redis, "t1_a")).toBe(false);
    expect(redis.expires.get(seenKey("t1_a"))).toBe(SEEN_TTL);
  });
});
