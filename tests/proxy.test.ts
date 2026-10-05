import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST, GET } from "@/app/engine/[...path]/route";
import { refuse } from "@/lib/guard";

// The proxy to the engine: only this app's own page, on this machine, gets through.

const ctx = { params: Promise.resolve({ path: ["strategies"] }) };
const BODY = JSON.stringify({ filename: "evil.py", code: "import os" });

function req(method: string, headers: Record<string, string>, body?: BodyInit) {
  return new Request("http://127.0.0.1:3200/engine/strategies", { method, headers, body });
}

let sent: { url: string; init: RequestInit }[] = [];

beforeEach(() => {
  sent = [];
  vi.stubEnv("WEB_PORT", "3200");
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    sent.push({ url, init });
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("engine proxy", () => {
  it("refuses a Host that isn't this machine (DNS rebinding)", async () => {
    const r = await GET(req("GET", { host: "evil.example:3200" }), ctx);
    expect(r.status).toBe(403);
    expect((await POST(req("POST", { host: "attacker.127.0.0.1.nip.io:3200", "sec-fetch-site": "same-origin" }, BODY), ctx)).status).toBe(403);
    expect((await GET(req("GET", { host: "127.0.0.1:9999" }), ctx)).status).toBe(403); // another port
    expect(sent).toEqual([]);
  });

  it("refuses a POST from another website", async () => {
    const cross = req("POST", { host: "127.0.0.1:3200", "sec-fetch-site": "cross-site", origin: "https://evil.example" }, BODY);
    expect((await POST(cross, ctx)).status).toBe(403);
    const wrongOrigin = req("POST", { host: "127.0.0.1:3200", origin: "https://evil.example" }, BODY);
    expect((await POST(wrongOrigin, ctx)).status).toBe(403);
    expect(sent).toEqual([]);
  });

  it("refuses a POST that says neither Origin nor Sec-Fetch-Site", async () => {
    expect((await POST(req("POST", { host: "127.0.0.1:3200" }, BODY), ctx)).status).toBe(403);
    expect(sent).toEqual([]);
  });

  it("passes a same-origin POST, with the proxy header and only the content-type that came in", async () => {
    const ok = await POST(req("POST", { host: "127.0.0.1:3200", "sec-fetch-site": "same-origin", "content-type": "application/json" }, BODY), ctx);
    expect(ok.status).toBe(200);
    expect(sent[0].url).toMatch(/\/strategies$/);
    expect(sent[0].init.headers).toEqual({ "x-spread-proxy": "1", "content-type": "application/json" });

    // A body with no type (a Blob from another page) isn't labelled JSON on its way through.
    await POST(req("POST", { host: "localhost:3200", origin: "http://localhost:3200" }, new Blob([BODY])), ctx);
    expect(sent[1].init.headers).toEqual({ "x-spread-proxy": "1" });
  });

  it("lets this app's own page read", async () => {
    for (const host of ["127.0.0.1:3200", "localhost:3200", "[::1]:3200"]) {
      expect(refuse(req("GET", { host }))).toBeNull();
    }
  });
});
