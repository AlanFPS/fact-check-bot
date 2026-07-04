import type { RedisLike } from "../src/store/redis.js";

export const baseSettings = {
  llmApiKey: "llm-key",
  llmBaseUrl: "https://openrouter.ai/api/v1",
  llmModel: "meta-llama/llama-3.3-70b-instruct:free",
  llmTemperature: 0,
  llmMaxTokens: 700,
  llmTimeoutMs: 60000,
  llmMaxRetries: 2,
  googleFactCheckApiKey: null,
  googleFactCheckLanguage: "en",
  googleFactCheckMaxClaims: 3,
  googleFactCheckTimeoutMs: 10000,
  searchApiKey: null,
  searchMaxResults: 5,
  searchSnippetChars: 500,
  searchTimeoutMs: 15000,
  botTrigger: "!factcheck",
  maxClaimChars: 500,
  maxReplyChars: 9500,
  rateLimitPerUserPerHour: 3,
  rateLimitGlobalPerHour: 30,
  dryRun: true,
  ignoreBots: true,
  enableVerdictCache: true,
  cacheTtlSeconds: 604800
};

export class FakeRedis implements RedisLike {
  values = new Map<string, string>();
  expires = new Map<string, number>();

  async get(key: string): Promise<string | null> {
    return this.values.get(key) ?? null;
  }

  async set(key: string, value: string, opts?: { nx?: boolean }): Promise<string | null> {
    if (opts?.nx && this.values.has(key)) {
      return null;
    }
    this.values.set(key, value);
    return "OK";
  }

  async incrBy(key: string, n: number): Promise<number> {
    const next = Number(this.values.get(key) ?? "0") + n;
    this.values.set(key, String(next));
    return next;
  }

  async expire(key: string, seconds: number): Promise<void> {
    this.expires.set(key, seconds);
  }
}

export function jsonResponse(payload: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(payload), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" }
  });
}
