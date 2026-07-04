import type { Settings } from "../core/config.js";
import type { GoogleClaim, GoogleReview } from "../core/models.js";
import { isRecord } from "../core/models.js";
import { isHttpUrl } from "../core/rendering.js";

export interface GoogleDeps {
  fetchFn?: typeof fetch;
}

export class GoogleFactCheckClient {
  static ENDPOINT = "https://factchecktools.googleapis.com/v1alpha1/claims:search";

  private fetchFn: typeof fetch;

  constructor(private settings: Settings, deps: GoogleDeps = {}) {
    this.fetchFn = deps.fetchFn ?? fetch;
  }

  get enabled(): boolean {
    return !!this.settings.googleFactCheckApiKey;
  }

  async search(query: string): Promise<GoogleClaim[]> {
    if (!this.enabled || !query) {
      return [];
    }
    try {
      const url = new URL(GoogleFactCheckClient.ENDPOINT);
      url.search = new URLSearchParams({
        query,
        key: this.settings.googleFactCheckApiKey ?? "",
        languageCode: this.settings.googleFactCheckLanguage,
        pageSize: String(this.settings.googleFactCheckMaxClaims)
      }).toString();
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), this.settings.googleFactCheckTimeoutMs);
      try {
        const response = await this.fetchFn(url, { signal: controller.signal });
        if (!response.ok) {
          console.warn("Google fact-check failed with status", response.status);
          return [];
        }
        const data = (await response.json()) as unknown;
        const rawClaims = isRecord(data) && Array.isArray(data.claims) ? data.claims : [];
        const claims: GoogleClaim[] = [];
        for (const raw of rawClaims) {
          if (!isRecord(raw)) {
            continue;
          }
          try {
            const claim = mapClaim(raw);
            if (claim !== null) {
              claims.push(claim);
            }
          } catch {
            continue;
          }
        }
        return claims.slice(0, this.settings.googleFactCheckMaxClaims);
      } finally {
        clearTimeout(timeout);
      }
    } catch (error) {
      console.warn("Google fact-check failed", error instanceof Error ? error.name : "Error");
      return [];
    }
  }
}

export function mapClaim(raw: Record<string, unknown>): GoogleClaim | null {
  const text = String(raw.text ?? "").trim();
  if (!text) {
    return null;
  }
  const rawReviews = Array.isArray(raw.claimReview) ? raw.claimReview : [];
  const reviews: GoogleReview[] = [];
  for (const review of rawReviews) {
    if (!isRecord(review)) {
      continue;
    }
    const url = String(review.url ?? "").trim();
    if (!isHttpUrl(url)) {
      continue;
    }
    const publisher = isRecord(review.publisher) ? review.publisher : {};
    reviews.push({
      publisher: String(publisher.name ?? publisher.site ?? "Unknown").trim(),
      textualRating: String(review.textualRating ?? "").trim(),
      url,
      title: optionalString(review.title),
      reviewDate: optionalString(review.reviewDate)
    });
  }
  if (reviews.length === 0) {
    return null;
  }
  return {
    text,
    claimant: optionalString(raw.claimant),
    reviews
  };
}

function optionalString(value: unknown): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  const text = String(value).trim();
  return text || null;
}
