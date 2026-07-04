import { describe, expect, it } from "vitest";

import { extractJsonObject } from "../src/core/jsonParse.js";

describe("jsonParse", () => {
  it("parses plain, fenced, and prefixed JSON", () => {
    expect(extractJsonObject('{"a":1}')).toEqual({ a: 1 });
    expect(extractJsonObject('```json\n{"a":1}\n```')).toEqual({ a: 1 });
    expect(extractJsonObject('thinking...\n{"a":{"b":2}}\ntrailing')).toEqual({
      a: { b: 2 }
    });
    expect(extractJsonObject('prefix {"a":"brace } inside"} junk')).toEqual({
      a: "brace } inside"
    });
  });

  it("rejects invalid and non-standard JSON", () => {
    expect(() => extractJsonObject("not json")).toThrow();
    expect(() => extractJsonObject('{"confidence":NaN}')).toThrow();
  });
});
