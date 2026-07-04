import { describe, expect, it } from "vitest";

import { Pipeline, type PipelineCache } from "../src/core/pipeline.js";
import { Verdict, type Evidence, type FactCheckResult, type GoogleClaim, type PipelineOutcome } from "../src/core/models.js";
import { baseSettings } from "./helpers.js";

const evidence: Evidence[] = [{ index: 1, title: "One", url: "https://example.com", snippet: "One" }];
const result: FactCheckResult = {
  verdict: Verdict.TRUE,
  confidence: 0.9,
  reasoning: "Supported.",
  citedSources: [1]
};
const googleClaims: GoogleClaim[] = [
  {
    text: "Claim.",
    reviews: [{ publisher: "Publisher", textualRating: "False", url: "https://example.com" }]
  }
];

class FakeLlm {
  extractCalls: string[] = [];
  factCalls: Array<[string, Evidence[]]> = [];
  constructor(private raises = false) {}
  async extractClaim(raw: string): Promise<string> {
    this.extractCalls.push(raw);
    return "Extracted claim.";
  }
  async factCheck(claim: string, ev: Evidence[]): Promise<FactCheckResult> {
    if (this.raises) {
      throw new Error("down");
    }
    this.factCalls.push([claim, ev]);
    return result;
  }
}

class FakeGoogle {
  enabled = true;
  queries: string[] = [];
  constructor(private claims: GoogleClaim[]) {}
  async search(query: string): Promise<GoogleClaim[]> {
    this.queries.push(query);
    return this.claims;
  }
}

class FakeSearch {
  enabled = true;
  queries: string[] = [];
  constructor(private hits: Evidence[]) {}
  async search(query: string): Promise<Evidence[]> {
    this.queries.push(query);
    return this.hits;
  }
}

describe("pipeline", () => {
  it("resolves inline and parent-derived claims", async () => {
    const llm = new FakeLlm();
    const pipeline = new Pipeline({ settings: baseSettings, llm: llm as never });
    expect(
      await pipeline.resolveClaim(
        { itemId: "t1", author: "a", inlineQuery: "Inline claim.", permalink: "", source: "comment_submit" },
        async () => {
          throw new Error("should not fetch parent");
        }
      )
    ).toBe("Inline claim.");
    expect(
      await pipeline.resolveClaim(
        { itemId: "t1", author: "a", inlineQuery: "", permalink: "", source: "comment_submit" },
        async () => "Parent text."
      )
    ).toBe("Extracted claim.");
    expect(llm.extractCalls).toEqual(["Parent text."]);
  });

  it("uses Google hits without search or LLM", async () => {
    const llm = new FakeLlm();
    const google = new FakeGoogle(googleClaims);
    const search = new FakeSearch(evidence);
    const pipeline = new Pipeline({
      settings: baseSettings,
      llm: llm as never,
      google: google as never,
      search: search as never
    });
    const outcome = await pipeline.run("claim");
    expect(outcome.source).toBe("google");
    expect(search.queries).toEqual([]);
    expect(llm.factCalls).toEqual([]);
  });

  it("falls back to search and LLM", async () => {
    const llm = new FakeLlm();
    const google = new FakeGoogle([]);
    const search = new FakeSearch(evidence);
    const pipeline = new Pipeline({
      settings: baseSettings,
      llm: llm as never,
      google: google as never,
      search: search as never
    });
    const outcome = await pipeline.run("claim");
    expect(outcome.source).toBe("llm");
    expect(search.queries).toEqual(["claim"]);
    expect(llm.factCalls).toEqual([["claim", evidence]]);
  });

  it("supports cache hit and miss", async () => {
    const cached: PipelineOutcome = {
      source: "llm",
      claim: "cached",
      googleClaims: [],
      llmResult: result,
      evidence: []
    };
    const cache: PipelineCache = {
      key: async () => "cache-key",
      get: async () => cached,
      put: async () => undefined
    };
    const llm = new FakeLlm();
    const hit = await new Pipeline({ settings: baseSettings, llm: llm as never, cache }).run("claim");
    expect(hit).toBe(cached);
    expect(llm.factCalls).toEqual([]);

    const writes: PipelineOutcome[] = [];
    const missCache: PipelineCache = {
      key: async () => "cache-key",
      get: async () => null,
      put: async (_key, outcome) => {
        writes.push(outcome);
      }
    };
    await new Pipeline({ settings: baseSettings, llm: llm as never, cache: missCache }).run("claim");
    expect(writes).toHaveLength(1);
  });
});
