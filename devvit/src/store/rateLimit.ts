import type { Settings } from "../core/config.js";
import type { RedisLike } from "./redis.js";

export type RateLimitReason = "" | "per-user rate limit" | "global rate limit";

export interface RateLimitResult {
  allowed: boolean;
  reason: RateLimitReason;
}

export async function checkAndReserve(
  redis: RedisLike,
  author: string | null,
  settings: Settings,
  nowMs: number
): Promise<RateLimitResult> {
  if (!author) {
    return { allowed: false, reason: "per-user rate limit" };
  }
  const bucket = Math.floor(nowMs / 3_600_000);
  const globalKey = `rl:global:${bucket}`;
  const userKey = `rl:user:${author}:${bucket}`;
  const userCount = await redis.incrBy(userKey, 1);
  if (userCount === 1) {
    await redis.expire(userKey, 7200);
  }
  if (userCount > settings.rateLimitPerUserPerHour) {
    return { allowed: false, reason: "per-user rate limit" };
  }
  const globalCount = await redis.incrBy(globalKey, 1);
  if (globalCount === 1) {
    await redis.expire(globalKey, 7200);
  }
  if (globalCount > settings.rateLimitGlobalPerHour) {
    return { allowed: false, reason: "global rate limit" };
  }
  return { allowed: true, reason: "" };
}
