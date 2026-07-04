import { describe, expect, it } from "vitest";

import {
  containsTrigger,
  extractInlineQuery,
  isIgnorableAuthor,
  normalizeClaim,
  stripQuotedAndCode
} from "../src/core/triggers.js";

describe("triggers", () => {
  it("detects triggers case-insensitively and handles empty input", () => {
    expect(containsTrigger("please !FACTCHECK this", "!factcheck")).toBe(true);
    expect(containsTrigger("", "!factcheck")).toBe(false);
    expect(containsTrigger(null, "!factcheck")).toBe(false);
  });

  it("strips quoted and code trigger occurrences", () => {
    const body = [
      "> !factcheck quoted",
      "```ts",
      "!factcheck coded",
      "```",
      "inline `!factcheck span`",
      "real !factcheck real claim"
    ].join("\n");
    const stripped = stripQuotedAndCode(body);
    expect(stripped).not.toContain("quoted");
    expect(stripped).not.toContain("coded");
    expect(stripped).not.toContain("span");
    expect(extractInlineQuery(stripped, "!factcheck")).toBe("real claim");
  });

  it("extracts and normalizes inline query", () => {
    expect(extractInlineQuery("x !factcheck: 'The Sky Is Blue'", "!factcheck")).toBe(
      "The Sky Is Blue"
    );
    expect(extractInlineQuery("!FACTCHECK " + "word ".repeat(20), "!factcheck", 12)).toBe(
      "word word"
    );
  });

  it("filters ignorable authors", () => {
    expect(isIgnorableAuthor(null, "factbot", true)).toBe(true);
    expect(isIgnorableAuthor("FactBot", "factbot", true)).toBe(true);
    expect(isIgnorableAuthor("helperbot", "factbot", true)).toBe(true);
    expect(isIgnorableAuthor("helperbot", "factbot", false)).toBe(false);
    expect(isIgnorableAuthor("alice", "factbot", true)).toBe(false);
  });

  it("normalizes claims", () => {
    expect(normalizeClaim('> "The   earth\n is round"`', 100)).toBe("The earth is round");
    expect(normalizeClaim("   ", 100)).toBe("");
    expect(normalizeClaim("alpha beta gamma", 10)).toBe("alpha beta");
  });
});
