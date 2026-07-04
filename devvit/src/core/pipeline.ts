import type { GoogleFactCheckClient } from "../clients/google.js";
import type { LlmClient } from "../clients/llm.js";
import type { SearchClient } from "../clients/search.js";
import type { Settings } from "./config.js";
import type { PipelineOutcome, TriggerContext } from "./models.js";
import { normalizeClaim } from "./triggers.js";

export interface PipelineCache {
  get(key: string): Promise<PipelineOutcome | null>;
  put(key: string, outcome: PipelineOutcome): Promise<void>;
  key(normalizedClaim: string, tierScope: string): Promise<string>;
}

export interface PipelineDeps {
  settings: Settings;
  llm: LlmClient;
  google?: GoogleFactCheckClient | null;
  search?: SearchClient | null;
  cache?: PipelineCache | null;
}

export class Pipeline {
  constructor(private deps: PipelineDeps) {}

  async resolveClaim(
    ctx: TriggerContext,
    parentTextGetter: () => Promise<string | null>
  ): Promise<string> {
    const inline = normalizeClaim(ctx.inlineQuery, this.deps.settings.maxClaimChars);
    if (inline) {
      return inline;
    }
    const parentText = await parentTextGetter();
    if (!parentText) {
      return "";
    }
    return normalizeClaim(
      await this.deps.llm.extractClaim(parentText),
      this.deps.settings.maxClaimChars
    );
  }

  async run(claim: string): Promise<PipelineOutcome> {
    const normalizedClaim = normalizeClaim(claim, this.deps.settings.maxClaimChars);
    const scope = tierScope(this.deps.settings, this.deps.google ?? null, this.deps.search ?? null);
    const cache = this.deps.settings.enableVerdictCache ? this.deps.cache : null;
    const key = cache ? await cache.key(normalizedClaim, scope) : "";
    if (cache) {
      const cached = await cache.get(key);
      if (cached) {
        return cached;
      }
    }
    const outcome = await this.runUncached(claim);
    if (cache) {
      await cache.put(key, outcome);
    }
    return outcome;
  }

  private async runUncached(claim: string): Promise<PipelineOutcome> {
    const google = this.deps.google;
    if (google?.enabled) {
      const googleClaims = await google.search(claim);
      if (googleClaims.length > 0) {
        return { source: "google", claim, googleClaims, llmResult: null, evidence: [] };
      }
    }
    const search = this.deps.search;
    const evidence = search?.enabled ? await search.search(claim) : [];
    const result = await this.deps.llm.factCheck(claim, evidence);
    return { source: "llm", claim, googleClaims: [], llmResult: result, evidence };
  }
}

export function tierScope(
  settings: Settings,
  google: GoogleFactCheckClient | null,
  search: SearchClient | null
): string {
  let scope = google?.enabled
    ? `google-first:${settings.googleFactCheckLanguage}:${settings.googleFactCheckMaxClaims}`
    : "llm-only";
  if (search?.enabled) {
    scope += ":search";
  }
  return scope;
}
