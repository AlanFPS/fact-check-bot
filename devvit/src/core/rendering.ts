import type { Settings } from "./config.js";
import type { Evidence, FactCheckResult, GoogleClaim, PipelineOutcome, Verdict } from "./models.js";
import { Verdict as VerdictEnum } from "./models.js";

const VERDICT_EMOJI: Record<Verdict, string> = {
  [VerdictEnum.TRUE]: "✅",
  [VerdictEnum.MOSTLY_TRUE]: "✅",
  [VerdictEnum.MIXED]: "⚖️",
  [VerdictEnum.MOSTLY_FALSE]: "❌",
  [VerdictEnum.FALSE]: "❌",
  [VerdictEnum.UNVERIFIABLE]: "❓"
};

const DISCLAIMER =
  "^(🤖 I'm an experimental, AI-powered bot. This is an automated, LLM-generated " +
  "assessment based on a quick web search, NOT authoritative fact-checking. Verify " +
  "important claims yourself.)";
const LLM_ONLY_DISCLAIMER =
  "^(🤖 I'm an experimental, AI-powered bot. This assessment comes from an AI model's " +
  "own training data with NO live sources consulted, so it may be outdated or wrong. " +
  "Verify important claims yourself.)";
const GOOGLE_DISCLAIMER =
  "^(📰 These are real, published fact-checks from independent publishers, retrieved " +
  "via Google's Fact Check Tools API and collected by a bot. Ratings and wording are " +
  "each publisher's own, not the bot's opinion or an AI assessment.)";
const NO_CLAIM_DISCLAIMER =
  "^(🤖 I'm an experimental, AI-powered bot, not an authoritative fact-checker.)";

function footer(trigger: string): string {
  return `^(Usage: reply to any comment with \`${trigger} <claim>\`, or just \`${trigger}\` to check the comment you're replying to.)`;
}

export function renderOutcome(outcome: PipelineOutcome, settings: Settings): string {
  if (outcome.source === "google") {
    return renderGoogleReply(outcome.claim, outcome.googleClaims, settings);
  }
  if (outcome.llmResult === null) {
    throw new Error("llmResult is required for LLM outcomes");
  }
  return renderReply(outcome.claim, outcome.llmResult, outcome.evidence, settings);
}

export function renderReply(
  claim: string,
  result: FactCheckResult,
  evidence: Evidence[],
  settings: Settings
): string {
  const confidence = Math.round(result.confidence * 100);
  const header = `**Fact check: ${VERDICT_EMOJI[result.verdict]} ${result.verdict}**  (confidence: ${confidence}%)`;
  const sourceLines = sourceLinesFor(result, evidence);
  return fitToLimit({
    header,
    claim,
    reasoning: result.reasoning,
    sourceLines,
    disclaimer: evidence.length === 0 ? LLM_ONLY_DISCLAIMER : DISCLAIMER,
    footerText: footer(settings.botTrigger),
    maxChars: settings.maxReplyChars
  });
}

export function renderGoogleReply(
  claim: string,
  googleClaims: GoogleClaim[],
  settings: Settings
): string {
  return fitGoogleToLimit(
    claim,
    googleRows(googleClaims, settings.googleFactCheckMaxClaims),
    footer(settings.botTrigger),
    settings.maxReplyChars
  );
}

export function renderNoClaimReply(settings: Settings): string {
  return (
    `I couldn't find a claim to check. Reply with \`${settings.botTrigger} <claim>\`, or use just\n` +
    `\`${settings.botTrigger}\` as a reply to the comment or post you want checked.\n\n` +
    "---\n" +
    NO_CLAIM_DISCLAIMER
  );
}

function sourceLinesFor(result: FactCheckResult, evidence: Evidence[]): string[] {
  if (evidence.length === 0) {
    return [];
  }
  const byIndex = new Map(evidence.map((item) => [item.index, item]));
  let selected = result.citedSources
    .map((index) => byIndex.get(index))
    .filter((item): item is Evidence => item !== undefined && isHttpUrl(item.url));
  if (selected.length === 0) {
    selected = evidence.filter((item) => isHttpUrl(item.url)).slice(0, 5);
  }
  return selected.map(
    (item, index) => `${index + 1}. [${escapeMarkdownTitle(item.title)}](${item.url})`
  );
}

function googleRows(googleClaims: GoogleClaim[], maxRows: number): string[] {
  const rows: string[] = [];
  for (const googleClaim of googleClaims) {
    for (const review of googleClaim.reviews) {
      if (!isHttpUrl(review.url)) {
        continue;
      }
      rows.push(
        `| ${escapeTableCell(truncateTableText(googleClaim.text, 200))} | ${escapeTableCell(
          review.textualRating || "—"
        )} | [${escapeTableCell(review.publisher)}](${review.url}) |`
      );
      if (rows.length >= maxRows) {
        return rows;
      }
    }
  }
  return rows;
}

export function escapeMarkdownTitle(title: string): string {
  return title
    .replace(/\\/g, "\\\\")
    .replace(/\[/g, "\\[")
    .replace(/\]/g, "\\]")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)");
}

export function isHttpUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function escapeTableCell(text: string): string {
  return escapeMarkdownTitle(collapseTableText(text)).replace(/\|/g, "\\|");
}

function collapseTableText(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

function truncateTableText(text: string, maxChars: number): string {
  const collapsed = collapseTableText(text);
  if (collapsed.length <= maxChars) {
    return collapsed;
  }
  let truncated = collapsed.slice(0, maxChars - 1).trimEnd();
  if (truncated.includes(" ")) {
    truncated = truncated.split(" ").slice(0, -1).join(" ").trimEnd();
  }
  return `${truncated}…`;
}

function fitGoogleToLimit(
  claim: string,
  rows: string[],
  footerText: string,
  maxChars: number
): string {
  const currentRows = [...rows];
  while (true) {
    const reply = assembleGoogleReply(claim, currentRows, footerText);
    if (reply.length <= maxChars || currentRows.length === 0) {
      return reply.slice(0, maxChars);
    }
    currentRows.pop();
  }
}

function assembleGoogleReply(claim: string, rows: string[], footerText: string): string {
  let table = "| Claim | Rating | Source |\n|---|---|---|";
  if (rows.length > 0) {
    table += `\n${rows.join("\n")}`;
  }
  return (
    "**Published fact-checks found** 📰\n\n" +
    `> ${claim}\n\n` +
    `${table}\n\n` +
    "---\n" +
    `${GOOGLE_DISCLAIMER}\n\n` +
    footerText
  ).trim();
}

function fitToLimit(args: {
  header: string;
  claim: string;
  reasoning: string;
  sourceLines: string[];
  disclaimer: string;
  footerText: string;
  maxChars: number;
}): string {
  const lines = [...args.sourceLines];
  while (true) {
    const reply = assembleReply({ ...args, sourceLines: lines });
    if (reply.length <= args.maxChars) {
      return reply;
    }
    if (lines.length > 0) {
      lines.pop();
      continue;
    }
    const fixed = assembleReply({ ...args, reasoning: "", sourceLines: [] });
    const available = Math.max(args.maxChars - fixed.length - 1, 0);
    if (available <= 1) {
      return fixed.slice(0, args.maxChars);
    }
    return assembleReply({
      ...args,
      reasoning: `${args.reasoning.slice(0, available - 1).trimEnd()}…`,
      sourceLines: []
    }).slice(0, args.maxChars);
  }
}

function assembleReply(args: {
  header: string;
  claim: string;
  reasoning: string;
  sourceLines: string[];
  disclaimer: string;
  footerText: string;
}): string {
  const sources =
    args.sourceLines.length > 0
      ? `**Sources**\n${args.sourceLines.join("\n")}`
      : "*No web sources were found for this claim.*";
  return (
    `${args.header}\n\n` +
    `> ${args.claim}\n\n` +
    `${args.reasoning}\n\n` +
    `${sources}\n\n` +
    "---\n" +
    `${args.disclaimer}\n\n` +
    args.footerText
  ).trim();
}
