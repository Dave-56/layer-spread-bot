import { ENGINE_URL } from "@/lib/engine";

// /engine/* → the local engine, streamed through unchanged. Both run on this machine.
export const dynamic = "force-dynamic";

async function forward(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const url = new URL(request.url);
  const target = `${ENGINE_URL}/${path.map(encodeURIComponent).join("/")}${url.search}`;
  try {
    const res = await fetch(target, {
      method: request.method,
      headers: { "content-type": request.headers.get("content-type") ?? "application/json" },
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
