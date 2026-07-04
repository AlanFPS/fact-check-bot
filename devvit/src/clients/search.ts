import type { Settings } from "../core/config.js";
import type { Evidence } from "../core/models.js";
import { isRecord } from "../core/models.js";

export interface SearchDeps {
  fetchFn?: typeof fetch;
}

export class SearchClient {
  static ENDPOINT = "https://api.tavily.com/search";
  private fetchFn: typeof fetch;

  constructor(private settings: Settings, deps: SearchDeps = {}) {
    this.fetchFn = deps.fetchFn ?? fetch;
  }

  get enabled(): boolean {
    return !!this.settings.searchApiKey;
  }

  async search(query: string): Promise<Evidence[]> {
    if (!this.enabled || !query) {
      return [];
    }
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), this.settings.searchTimeoutMs);
      try {
        const response = await this.fetchFn(SearchClient.ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            api_key: this.settings.searchApiKey,
            query,
            max_results: this.settings.searchMaxResults,
            search_depth: "basic"
          })
        });
        if (!response.ok) {
          console.warn("Search failed with status", response.status);
          return [];
        }
        const data = (await response.json()) as unknown;
        const results = isRecord(data) && Array.isArray(data.results) ? data.results : [];
        const seenUrls = new Set<string>();
        const evidence: Evidence[] = [];
        for (const raw of results) {
          if (!isRecord(raw)) {
            continue;
          }
          const url = String(raw.url ?? "");
          if (seenUrls.has(url)) {
            continue;
          }
          seenUrls.add(url);
          evidence.push({
            index: evidence.length + 1,
            title: String(raw.title ?? ""),
            url,
            snippet: truncate(String(raw.content ?? ""), this.settings.searchSnippetChars)
          });
        }
        return evidence;
      } finally {
        clearTimeout(timeout);
      }
    } catch (error) {
      console.warn("Search failed", error instanceof Error ? error.name : "Error");
      return [];
    }
  }
}

export function truncate(text: string, n: number): string {
  if (text.length <= n) {
    return text;
  }
  if (n <= 1) {
    return "…".slice(0, n);
  }
  let truncated = text.slice(0, n - 1).trimEnd();
  if (truncated.includes(" ")) {
    truncated = truncated.split(" ").slice(0, -1).join(" ").trimEnd();
  }
  return `${truncated}…`;
}
