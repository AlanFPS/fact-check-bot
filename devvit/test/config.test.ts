import { describe, expect, it, vi } from "vitest";

import { loadSettings, type SettingsGetter } from "../src/core/config.js";

describe("config", () => {
  it("validates llmBaseUrl against HTTPS allowlisted hosts", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const getter: SettingsGetter = async <T>(name: string): Promise<T | undefined> => {
      if (name === "llmBaseUrl") {
        return "http://evil.example/v1" as T;
      }
      if (name === "llmApiKey") {
        return "key" as T;
      }
      return undefined;
    };
    const settings = await loadSettings(getter);
    expect(settings.llmBaseUrl).toBe("https://openrouter.ai/api/v1");
    expect(warn).toHaveBeenCalledWith("Invalid llmBaseUrl setting; falling back to default");
    warn.mockRestore();
  });

  it("keeps documented allowlisted LLM providers", async () => {
    const getter: SettingsGetter = async <T>(name: string): Promise<T | undefined> =>
      name === "llmBaseUrl"
        ? ("https://generativelanguage.googleapis.com/v1beta/openai/" as T)
        : undefined;
    const settings = await loadSettings(getter);
    expect(settings.llmBaseUrl).toBe("https://generativelanguage.googleapis.com/v1beta/openai");
  });
});
