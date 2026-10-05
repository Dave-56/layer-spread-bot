import type Anthropic from "@anthropic-ai/sdk";
import { chat } from "@/lib/agent";

// POST /api/chat {"messages":[...]} → newline-delimited JSON events (see ChatEvent).
// The browser keeps the conversation and sends it back each turn, unchanged.
export const maxDuration = 300;

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as { messages?: Anthropic.MessageParam[] } | null;
  if (!body?.messages?.length) return Response.json({ error: "send messages" }, { status: 400 });
  if (!process.env.ANTHROPIC_API_KEY && !process.env.OPENROUTER_API_KEY) {
    return Response.json(
      { error: "The chat needs your own LLM key: add ANTHROPIC_API_KEY or OPENROUTER_API_KEY to .env, then restart." },
      { status: 400 },
    );
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      try {
        for await (const event of chat(body.messages!)) controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
      } catch (err) {
        console.error(err instanceof Error ? err.message : "chat failed");
        const message = err instanceof Error ? err.message : "Something went wrong";
        controller.enqueue(encoder.encode(JSON.stringify({ type: "error", message }) + "\n"));
      }
      controller.close();
    },
  });
  return new Response(stream, { headers: { "content-type": "application/x-ndjson", "cache-control": "no-store" } });
}
