export const KNOWN_BOTS = new Set(["automoderator", "b0trank", "sneakpeekbot"]);

export function stripQuotedAndCode(body: string | null | undefined): string {
  if (!body) {
    return "";
  }
  return body
    .replace(/```[\s\S]*?```/g, "")
    .replace(/`[^`\n]*`/g, "")
    .replace(/^\s*>.*(?:\n|$)/gm, "");
}

export function containsTrigger(body: string | null | undefined, trigger: string): boolean {
  return !!body && !!trigger && body.toLowerCase().includes(trigger.toLowerCase());
}

export function extractInlineQuery(body: string, trigger: string, maxChars = 500): string {
  if (!body || !trigger) {
    return "";
  }
  const index = body.toLowerCase().indexOf(trigger.toLowerCase());
  if (index < 0) {
    return "";
  }
  const query = body.slice(index + trigger.length).replace(/^[\s:：'"`]+/, "");
  return normalizeClaim(query, maxChars);
}

export function isIgnorableAuthor(
  author: string | null,
  botUsername: string,
  ignoreBots: boolean
): boolean {
  if (author === null) {
    return true;
  }
  const normalized = author.toLowerCase();
  if (normalized === botUsername.toLowerCase()) {
    return true;
  }
  if (!ignoreBots) {
    return false;
  }
  return normalized.endsWith("bot") || KNOWN_BOTS.has(normalized);
}

export function normalizeClaim(text: string, maxChars: number): string {
  const cleaned = text
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*>\s?/, ""))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^[`"'“”‘’]+|[`"'“”‘’]+$/g, "");
  if (!cleaned) {
    return "";
  }
  if (cleaned.length <= maxChars) {
    return cleaned;
  }
  let truncated = cleaned.slice(0, maxChars).trimEnd();
  const next = cleaned.slice(maxChars, maxChars + 1);
  if (cleaned.length > maxChars && next.trim() && truncated.includes(" ")) {
    truncated = truncated.split(" ").slice(0, -1).join(" ").trimEnd();
  }
  return truncated;
}
