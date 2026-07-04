import { describe, expect, it, vi } from "vitest";

import { SearchClient } from "../src/clients/search.js";
import { baseSettings, jsonResponse } from "./helpers.js";

describe("search client", () => {
  it("returns empty without a key", async () => {
    const fetchFn = vi.fn();
    expect(await new SearchClient(baseSettings, { fetchFn }).search("claim")).toEqual([]);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("maps Tavily results, dedupes, and truncates", async () => {
    const fetchFn = vi.fn().mockResolvedValue(
      jsonResponse({
        results: [
          { title: "One", url: "https://example.com/one", content: "First source body." },
          { title: "Duplicate", url: "https://example.com/one", content: "Duplicate." },
          { title: "Two", url: "https://example.com/two", content: "Second source body." }
        ]
      })
    );
    const client = new SearchClient(
      { ...baseSettings, searchApiKey: "search-key", searchSnippetChars: 8 },
      { fetchFn }
    );
    const evidence = await client.search("claim");
    expect(evidence.map((item) => item.index)).toEqual([1, 2]);
    expect(evidence[0]?.snippet).toBe("First…");
  });

  it("returns empty on non-200 and thrown errors", async () => {
    expect(
      await new SearchClient(
        { ...baseSettings, searchApiKey: "key" },
        { fetchFn: vi.fn().mockResolvedValue(jsonResponse({}, { status: 500 })) }
      ).search("claim")
    ).toEqual([]);
    expect(
      await new SearchClient(
        { ...baseSettings, searchApiKey: "key" },
        { fetchFn: vi.fn().mockRejectedValue(new Error("down")) }
      ).search("claim")
    ).toEqual([]);
  });
});
