import { describe, expect, it, vi } from "vitest";

import { GoogleFactCheckClient, mapClaim } from "../src/clients/google.js";
import { baseSettings, jsonResponse } from "./helpers.js";

const fullClaim = {
  text: "The earth is flat.",
  claimant: "Someone",
  claimReview: [
    {
      publisher: { name: "Fact Publisher", site: "publisher.example" },
      textualRating: "False",
      url: "https://example.com/fact-check",
      title: "Earth fact check",
      reviewDate: "2026-01-01"
    }
  ]
};

describe("google client", () => {
  it("maps claims defensively", () => {
    expect(mapClaim(fullClaim)?.reviews[0]?.publisher).toBe("Fact Publisher");
    const fallback = mapClaim({
      text: "Claim.",
      claimReview: [
        { publisher: { site: "site.example" }, url: "ftp://bad" },
        { publisher: {}, url: "https://good.example" }
      ]
    });
    expect(fallback?.reviews).toHaveLength(1);
    expect(fallback?.reviews[0]?.publisher).toBe("Unknown");
    expect(mapClaim({ text: "Claim.", claimReview: [] })).toBeNull();
    expect(mapClaim({ text: "Claim.", claimReview: [{ url: "javascript:bad" }] })).toBeNull();
  });

  it("does not fetch when disabled or query is empty", async () => {
    const fetchFn = vi.fn();
    const client = new GoogleFactCheckClient(baseSettings, { fetchFn });
    expect(client.enabled).toBe(false);
    expect(await client.search("claim")).toEqual([]);
    expect(await new GoogleFactCheckClient({ ...baseSettings, googleFactCheckApiKey: "key" }, { fetchFn }).search("")).toEqual([]);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("maps, slices, and passes safe params", async () => {
    const fetchFn = vi.fn().mockResolvedValue(jsonResponse({ claims: [fullClaim, { ...fullClaim, text: "Two" }] }));
    const client = new GoogleFactCheckClient(
      { ...baseSettings, googleFactCheckApiKey: "secret", googleFactCheckMaxClaims: 1 },
      { fetchFn }
    );
    const claims = await client.search("earth flat");
    expect(claims).toHaveLength(1);
    const url = new URL(String(fetchFn.mock.calls[0]?.[0]));
    expect(url.searchParams.get("key")).toBe("secret");
    expect(url.searchParams.get("pageSize")).toBe("1");
  });

  it("returns empty on non-200 and thrown errors without logging API key", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const non200 = new GoogleFactCheckClient(
      { ...baseSettings, googleFactCheckApiKey: "secret" },
      { fetchFn: vi.fn().mockResolvedValue(jsonResponse({}, { status: 403 })) }
    );
    expect(await non200.search("claim")).toEqual([]);
    const throwing = new GoogleFactCheckClient(
      { ...baseSettings, googleFactCheckApiKey: "secret-test-key" },
      { fetchFn: vi.fn().mockRejectedValue(new Error("boom key=secret-test-key")) }
    );
    expect(await throwing.search("claim")).toEqual([]);
    expect(warn.mock.calls.flat().join(" ")).not.toContain("secret-test-key");
    warn.mockRestore();
  });
});
