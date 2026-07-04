import type { PipelineOutcome } from "../core/models.js";
import { isPipelineOutcome } from "../core/models.js";
import type { RedisLike } from "./redis.js";

export async function cacheKey(normalizedClaim: string, tierScope: string): Promise<string> {
  const bytes = new TextEncoder().encode(`${normalizedClaim}|${tierScope}`);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `cache:${hex}`;
}

export async function getCachedOutcome(
  redis: RedisLike,
  key: string
): Promise<PipelineOutcome | null> {
  try {
    const raw = await redis.get(key);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as unknown;
    return isValidPipelineOutcome(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export async function storeOutcome(
  redis: RedisLike,
  key: string,
  outcome: PipelineOutcome,
  ttlSeconds: number
): Promise<void> {
  await redis.set(key, JSON.stringify(outcome));
  await redis.expire(key, ttlSeconds);
}

function isValidPipelineOutcome(value: unknown): value is PipelineOutcome {
  if (!isPipelineOutcome(value) || typeof value.claim !== "string") {
    return false;
  }
  if (value.source === "google") {
    return Array.isArray(value.googleClaims);
  }
  return value.llmResult !== null && Array.isArray(value.evidence);
}
