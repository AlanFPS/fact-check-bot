import type { Settings } from "../core/config.js";
import { extractJsonObject } from "../core/jsonParse.js";
import type { Evidence, FactCheckResult } from "../core/models.js";
import { parseFactCheckResult, Verdict } from "../core/models.js";
import {
  buildEvidenceBlock,
  CLAIM_EXTRACTION_SYSTEM,
  claimExtractionUserTemplate,
  VERDICT_JSON_SCHEMA_TEXT,
  VERDICT_SYSTEM,
  verdictUserTemplate
} from "../core/prompts.js";
import { isRecord } from "../core/models.js";

export class LlmError extends Error {}

export interface LlmDeps {
  fetchFn?: typeof fetch;
}

export class LlmClient {
  private fetchFn: typeof fetch;

  constructor(private settings: Settings, deps: LlmDeps = {}) {
    this.fetchFn = deps.fetchFn ?? fetch;
  }

  async extractClaim(rawText: string): Promise<string> {
    const raw = await this.chat(
      CLAIM_EXTRACTION_SYSTEM,
      claimExtractionUserTemplate(rawText),
      true
    );
    try {
      const data = extractJsonObject(raw);
      return typeof data.claim === "string" ? data.claim.trim() : rawText.trim();
    } catch {
      return rawText.trim();
    }
  }

  async factCheck(claim: string, evidence: Evidence[]): Promise<FactCheckResult> {
    const baseUser = verdictUserTemplate(
      claim,
      buildEvidenceBlock(evidence),
      VERDICT_JSON_SCHEMA_TEXT
    );
    let user = baseUser;
    for (let attempt = 0; attempt <= this.settings.llmMaxRetries; attempt += 1) {
      const raw = await this.chat(VERDICT_SYSTEM, user, true);
      try {
        const data = extractJsonObject(raw);
        const result = parseFactCheckResult(data);
        return {
          ...result,
          citedSources: result.citedSources.filter((idx) => idx <= evidence.length)
        };
      } catch {
        if (attempt === this.settings.llmMaxRetries) {
          break;
        }
        user = `${baseUser}\n\nYour previous reply was not valid JSON matching the schema. Return ONLY the JSON object.`;
      }
    }
    return {
      verdict: Verdict.UNVERIFIABLE,
      confidence: 0,
      reasoning: "The model did not return a parseable verdict.",
      citedSources: []
    };
  }

  private async chat(system: string, user: string, jsonMode: boolean): Promise<string> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.settings.llmTimeoutMs);
    try {
      const response = await this.fetchFn(
        `${this.settings.llmBaseUrl.replace(/\/$/, "")}/chat/completions`,
        {
          method: "POST",
          signal: controller.signal,
          headers: {
            Authorization: `Bearer ${this.settings.llmApiKey}`,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://developers.reddit.com",
            "X-OpenRouter-Title": "fact-check-bot"
          },
          body: JSON.stringify({
            model: this.settings.llmModel,
            messages: [
              { role: "system", content: system },
              { role: "user", content: user }
            ],
            temperature: this.settings.llmTemperature,
            max_tokens: this.settings.llmMaxTokens,
            response_format: jsonMode ? { type: "json_object" } : undefined
          })
        }
      );
      clearTimeout(timeout);
      if (!response.ok) {
        throw new LlmError(`LLM unavailable: status ${response.status}`);
      }
      const data = (await response.json()) as unknown;
      if (!isRecord(data) || !Array.isArray(data.choices)) {
        return "";
      }
      const choice = data.choices[0];
      if (!isRecord(choice) || !isRecord(choice.message)) {
        return "";
      }
      return typeof choice.message.content === "string" ? choice.message.content : "";
    } catch (error) {
      clearTimeout(timeout);
      if (error instanceof LlmError) {
        throw error;
      }
      throw new LlmError(`LLM unavailable: ${error instanceof Error ? error.name : "Error"}`);
    }
  }
}
