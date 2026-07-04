export interface Settings {
  llmApiKey: string;
  llmBaseUrl: string;
  llmModel: string;
  llmTemperature: number;
  llmMaxTokens: number;
  llmTimeoutMs: number;
  llmMaxRetries: number;
  googleFactCheckApiKey: string | null;
  googleFactCheckLanguage: string;
  googleFactCheckMaxClaims: number;
  googleFactCheckTimeoutMs: number;
  searchApiKey: string | null;
  searchMaxResults: number;
  searchSnippetChars: number;
  searchTimeoutMs: number;
  botTrigger: string;
  maxClaimChars: number;
  maxReplyChars: number;
  rateLimitPerUserPerHour: number;
  rateLimitGlobalPerHour: number;
  dryRun: boolean;
  ignoreBots: boolean;
  enableVerdictCache: boolean;
  cacheTtlSeconds: number;
}

export type SettingsGetter = <T>(name: string) => Promise<T | undefined>;

const DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1";
const ALLOWED_LLM_HOSTS = new Set(["openrouter.ai", "generativelanguage.googleapis.com"]);

export async function loadSettings(getter: SettingsGetter): Promise<Settings> {
  const llmApiKey = trimString(await getter<string>("llmApiKey")) ?? "";
  return {
    llmApiKey,
    llmBaseUrl: validLlmBaseUrl(trimString(await getter<string>("llmBaseUrl"))),
    llmModel:
      trimString(await getter<string>("llmModel")) ??
      "meta-llama/llama-3.3-70b-instruct:free",
    llmTemperature: 0,
    llmMaxTokens: 700,
    llmTimeoutMs: 60000,
    llmMaxRetries: 2,
    googleFactCheckApiKey: trimString(await getter<string>("googleFactCheckApiKey")),
    googleFactCheckLanguage: "en",
    googleFactCheckMaxClaims: 3,
    googleFactCheckTimeoutMs: 10000,
    searchApiKey: trimString(await getter<string>("searchApiKey")),
    searchMaxResults: 5,
    searchSnippetChars: 500,
    searchTimeoutMs: 15000,
    botTrigger: trimString(await getter<string>("botTrigger")) ?? "!factcheck",
    maxClaimChars: 500,
    maxReplyChars: Math.min(9500, 10000),
    rateLimitPerUserPerHour: numberSetting(
      await getter<number>("rateLimitPerUserPerHour"),
      3
    ),
    rateLimitGlobalPerHour: numberSetting(
      await getter<number>("rateLimitGlobalPerHour"),
      30
    ),
    dryRun: booleanSetting(await getter<boolean>("dryRun"), true),
    ignoreBots: booleanSetting(await getter<boolean>("ignoreBots"), true),
    enableVerdictCache: booleanSetting(await getter<boolean>("enableVerdictCache"), true),
    cacheTtlSeconds: 604800
  };
}

function trimString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function numberSetting(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function booleanSetting(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function validLlmBaseUrl(value: string | null): string {
  if (value === null) {
    return DEFAULT_LLM_BASE_URL;
  }
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && ALLOWED_LLM_HOSTS.has(url.hostname)) {
      return value.replace(/\/$/, "");
    }
  } catch {
    // handled below
  }
  console.warn("Invalid llmBaseUrl setting; falling back to default");
  return DEFAULT_LLM_BASE_URL;
}
