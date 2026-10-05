import { describe, expect, it } from "vitest";
import { cents, money, pct } from "@/components/format";
import { errorText, ndjson } from "@/lib/engine";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
}

describe("ndjson", () => {
  it("joins lines split across chunks and keeps a last line without a newline", async () => {
    const out: unknown[] = [];
    for await (const e of ndjson(streamOf(['{"a":1}\n{"b"', ':2}\n\n{"c":3}']))) out.push(e);
    expect(out).toEqual([{ a: 1 }, { b: 2 }, { c: 3 }]);
  });
});

describe("errorText", () => {
  it("shows the SDK's message and hint", () => {
    expect(errorText({ error: { code: "auth_failed", message: "No key.", hint: "Set it.", venue: null } }, 400)).toBe("No key. Set it.");
  });
  it("shows FastAPI's detail", () => {
    expect(errorText({ detail: "Unknown match X." }, 404)).toBe("Unknown match X.");
  });
  it("says the engine may be down when there's no body", () => {
    expect(errorText(null, 502)).toMatch(/npm run dev/);
  });
});

describe("format", () => {
  it("prints prices and money the way traders read them", () => {
    expect(cents(0.54)).toBe("54¢");
    expect(cents(0.0125)).toBe("1.3¢");
    expect(cents(-0.005)).toBe("−0.5¢");
    expect(money(-0.15)).toBe("−$0.15");
    expect(money(3.1)).toBe("$3.10");
    expect(pct(1.23456, 3)).toBe("1.235%");
  });
});
