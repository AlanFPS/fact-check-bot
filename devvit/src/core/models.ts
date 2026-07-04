export enum Verdict {
  TRUE = "TRUE",
  MOSTLY_TRUE = "MOSTLY TRUE",
  MIXED = "MIXED",
  MOSTLY_FALSE = "MOSTLY FALSE",
  FALSE = "FALSE",
  UNVERIFIABLE = "UNVERIFIABLE"
}

export const MAX_REASONING_CHARS = 1500;

export interface Evidence {
  index: number;
  title: string;
  url: string;
  snippet: string;
}

export interface GoogleReview {
  publisher: string;
  textualRating: string;
  url: string;
  title?: string | null;
  reviewDate?: string | null;
}

export interface GoogleClaim {
  text: string;
  claimant?: string | null;
  reviews: GoogleReview[];
}

export interface FactCheckResult {
  verdict: Verdict;
  confidence: number;
  reasoning: string;
  citedSources: number[];
}

export interface PipelineOutcome {
  source: "google" | "llm";
  claim: string;
  googleClaims: GoogleClaim[];
  llmResult: FactCheckResult | null;
  evidence: Evidence[];
}

export interface TriggerContext {
  itemId: string;
  author: string | null;
  inlineQuery: string;
  permalink: string;
  source: "comment_submit";
}

const VERDICT_VALUES = new Set<string>(Object.values(Verdict));

export function parseFactCheckResult(data: unknown): FactCheckResult {
  if (!isRecord(data)) {
    throw new Error("Fact-check result must be an object");
  }
  const verdict = data.verdict;
  if (typeof verdict !== "string" || !VERDICT_VALUES.has(verdict)) {
    throw new Error("Invalid verdict");
  }
  const confidence = data.confidence;
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) {
    throw new Error("confidence must be finite");
  }
  const reasoning = String(data.reasoning ?? "");
  const citedRaw = Array.isArray(data.cited_sources) ? data.cited_sources : [];
  const seen = new Set<number>();
  const citedSources: number[] = [];
  for (const value of citedRaw) {
    if (!Number.isInteger(value) || value < 1 || seen.has(value)) {
      continue;
    }
    seen.add(value);
    citedSources.push(value);
  }
  return {
    verdict: verdict as Verdict,
    confidence: Math.min(Math.max(confidence, 0), 1),
    reasoning:
      reasoning.length <= MAX_REASONING_CHARS
        ? reasoning
        : `${reasoning.slice(0, MAX_REASONING_CHARS - 1).trimEnd()}…`,
    citedSources
  };
}

export function isPipelineOutcome(data: unknown): data is PipelineOutcome {
  return isRecord(data) && (data.source === "google" || data.source === "llm");
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
