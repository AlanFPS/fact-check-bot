import { describe, expect, it } from "vitest";

import { Verdict, type GoogleClaim, type PipelineOutcome } from "../src/core/models.js";
import { renderGoogleReply, renderNoClaimReply, renderOutcome, renderReply } from "../src/core/rendering.js";
import { baseSettings } from "./helpers.js";

describe("rendering", () => {
  it("renders LLM replies with sources and disclaimer", () => {
    const reply = renderReply(
      "The claim.",
      {
        verdict: Verdict.FALSE,
        confidence: 0.84,
        reasoning: "Sources contradict the claim.",
        citedSources: [2]
      },
      [
        { index: 1, title: "One", url: "https://example.com/one", snippet: "One" },
        { index: 2, title: "Two", url: "https://example.com/two", snippet: "Two" }
      ],
      baseSettings
    );
    expect(reply).toContain("**Fact check: ❌ FALSE**  (confidence: 84%)");
    expect(reply).toContain("> The claim.");
    expect(reply).toContain("1. [Two](https://example.com/two)");
    expect(reply).toContain("AI-powered bot");
  });

  it("uses the LLM-only disclaimer when no evidence exists", () => {
    const reply = renderReply(
      "Claim.",
      { verdict: Verdict.UNVERIFIABLE, confidence: 0, reasoning: "No evidence.", citedSources: [] },
      [],
      baseSettings
    );
    expect(reply).toContain("NO live sources consulted");
    expect(reply).toContain("*No web sources were found for this claim.*");
  });

  it("escapes sources and drops non-http URLs", () => {
    const reply = renderReply(
      "Claim.",
      { verdict: Verdict.MIXED, confidence: 0.5, reasoning: "Mixed.", citedSources: [] },
      [
        { index: 1, title: "A [bad](title)", url: "https://example.com", snippet: "" },
        { index: 2, title: "Bad", url: "javascript:alert(1)", snippet: "" }
      ],
      baseSettings
    );
    expect(reply).toContain("A \\[bad\\]\\(title\\)");
    expect(reply).not.toContain("javascript:");
  });

  it("renders Google table with escaping and row cap", () => {
    const claims: GoogleClaim[] = [
      {
        text: "A | claim [click](http://evil)",
        reviews: [
          { publisher: "Bad | Publisher", textualRating: "", url: "https://example.com/a" },
          { publisher: "Second", textualRating: "True", url: "https://example.com/b" }
        ]
      }
    ];
    const reply = renderGoogleReply("Original claim.", claims, { ...baseSettings, googleFactCheckMaxClaims: 1 });
    expect(reply).toContain("| Claim | Rating | Source |");
    expect(reply).toContain("A \\| claim \\[click\\]\\(http://evil\\)");
    expect(reply).toContain("[Bad \\| Publisher](https://example.com/a)");
    expect(reply).not.toContain("Second");
    expect(reply).toContain("published fact-checks");
  });

  it("dispatches outcomes and renders no-claim", () => {
    const googleOutcome: PipelineOutcome = {
      source: "google",
      claim: "Claim.",
      googleClaims: [
        { text: "Claim.", reviews: [{ publisher: "Pub", textualRating: "False", url: "https://e.com" }] }
      ],
      llmResult: null,
      evidence: []
    };
    expect(renderOutcome(googleOutcome, baseSettings)).toContain("Published fact-checks");
    expect(renderNoClaimReply(baseSettings)).toContain("I couldn't find a claim");
  });
});
