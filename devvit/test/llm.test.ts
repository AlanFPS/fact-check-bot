import { describe, expect, it, vi } from "vitest";

import { LlmClient, LlmError } from "../src/clients/llm.js";
import { Verdict } from "../src/core/models.js";
import { baseSettings, jsonResponse } from "./helpers.js";

function chatResponse(content: string): Response {
  return jsonResponse({ choices: [{ message: { content } }] });
}

describe("LLM client", () => {
  it("extracts claims or falls back to raw text", async () => {
    const fetchFn = vi.fn().mockResolvedValueOnce(chatResponse('{"claim":"The moon exists."}')).mockResolvedValueOnce(chatResponse("garbage"));
    const client = new LlmClient(baseSettings, { fetchFn });
    expect(await client.extractClaim("raw text")).toBe("The moon exists.");
    expect(await client.extractClaim("raw text")).toBe("raw text");
  });

  it("fact-checks valid JSON and filters cited sources", async () => {
    const fetchFn = vi.fn().mockResolvedValue(
      chatResponse('{"verdict":"FALSE","confidence":1.2,"reasoning":"No.","cited_sources":[1,2,2,0,9]}')
    );
    const client = new LlmClient(baseSettings, { fetchFn });
    const result = await client.factCheck("claim", [{ index: 1, title: "One", url: "https://e.com", snippet: "" }]);
    expect(result.verdict).toBe(Verdict.FALSE);
    expect(result.confidence).toBe(1);
    expect(result.citedSources).toEqual([1]);
  });

  it("retries bad JSON and falls back to unverifiable after exhaustion", async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(chatResponse("garbage"))
      .mockResolvedValueOnce(chatResponse('{"verdict":"TRUE","confidence":0.7,"reasoning":"Ok","cited_sources":[]}'));
    const client = new LlmClient(baseSettings, { fetchFn });
    expect((await client.factCheck("claim", [])).verdict).toBe(Verdict.TRUE);
    expect(fetchFn).toHaveBeenCalledTimes(2);

    const badFetch = vi.fn().mockImplementation(async () => chatResponse("bad"));
    const bad = new LlmClient({ ...baseSettings, llmMaxRetries: 1 }, { fetchFn: badFetch });
    const fallback = await bad.factCheck("claim", []);
    expect(fallback.verdict).toBe(Verdict.UNVERIFIABLE);
  });

  it("throws LlmError on non-2xx or network errors", async () => {
    await expect(
      new LlmClient(baseSettings, { fetchFn: vi.fn().mockResolvedValue(jsonResponse({}, { status: 500 })) }).factCheck("claim", [])
    ).rejects.toBeInstanceOf(LlmError);
    await expect(
      new LlmClient(baseSettings, { fetchFn: vi.fn().mockRejectedValue(new Error("down")) }).factCheck("claim", [])
    ).rejects.toBeInstanceOf(LlmError);
  });
});
