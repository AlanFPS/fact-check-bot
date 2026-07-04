export function extractJsonObject(text: string): Record<string, unknown> {
  const candidates = [text, stripCodeFence(text)];
  const balanced = firstBalancedObject(text);
  if (balanced !== null) {
    candidates.push(balanced);
  }
  for (const candidate of candidates) {
    const trimmed = candidate.trim();
    if (!trimmed) {
      continue;
    }
    try {
      const parsed = JSON.parse(trimmed);
      if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      continue;
    }
  }
  throw new Error("No JSON object found");
}

export function stripCodeFence(text: string): string {
  const stripped = text.trim();
  if (!stripped.startsWith("```")) {
    return stripped;
  }
  const lines = stripped.split(/\r?\n/);
  if (lines.length >= 3 && lines[lines.length - 1]?.trim() === "```") {
    return lines.slice(1, -1).join("\n").trim();
  }
  return stripped;
}

export function firstBalancedObject(text: string): string | null {
  const start = text.indexOf("{");
  if (start < 0) {
    return null;
  }
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let index = start; index < text.length; index += 1) {
    const char = text[index];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === '"') {
        inString = false;
      }
      continue;
    }
    if (char === '"') {
      inString = true;
    } else if (char === "{") {
      depth += 1;
    } else if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        return text.slice(start, index + 1);
      }
    }
  }
  return null;
}
