import { ENGINE_URL } from "@/lib/engine";
import { PROXY_HEADER, refuse } from "@/lib/guard";

// /engine/* → the local engine, streamed through unchanged. Both run on this machine. Only this app's
// own page may use it (lib/guard.ts): the engine places orders and adds strategy files.
export const dynamic = "force-dynamic";

async function forward(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const refused = refuse(request);
  if (refused) return refused;
  const { path } = await params;
  const url = new URL(request.url);
  const target = `${ENGINE_URL}/${path.map(encodeURIComponent).join("/")}${url.search}`;
  // Forward only the content-type that came in: the engine refuses a POST that isn't JSON.
  const headers: Record<string, string> = { [PROXY_HEADER]: "1" };
  const type = request.headers.get("content-type");
  if (type) headers["content-type"] = type;
  try {
    const res = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" ? undefined : await request.text(),
      cache: "no-store",
    });
    return new Response(res.body, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json", "cache-control": "no-store" },
    });
  } catch {
    return Response.json(
      { error: `The engine isn't running at ${ENGINE_URL}. Start it with npm run dev.` },
      { status: 502 },
    );
  }
}

export { forward as GET, forward as POST };
