import type { RedisLike } from "./redis.js";

export const SEEN_TTL = 2_592_000;

export function seenKey(commentId: string): string {
  return `seen:${commentId}`;
}

export async function markSeenIfNew(
  redis: RedisLike,
  commentId: string,
  ttlSeconds = SEEN_TTL
): Promise<boolean> {
  const key = seenKey(commentId);
  const result = await redis.set(key, "1", { nx: true });
  if (!result) {
    return false;
  }
  await redis.expire(key, ttlSeconds);
  return true;
}
