import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { engine, ENGINE_URL, ndjson, errorText, type BestResult, type MatchView, type ScanEvent, type ScanRow, type Verdict } from "./engine";

// The optional chat panel: Claude reads the question, calls the local engine (the uselayer SDK on
// this machine) and explains the result. It reads; it never places an order.

export interface Funnel {
  total: number;
  counts: Partial<Record<Verdict, number>>;
  rows: ScanRow[];
}

export type ChatEvent =
  | { type: "text"; delta: string }
  | { type: "status"; label: string }
  | { type: "matches"; matches: MatchView[] }
  | { type: "best"; best: BestResult & { match?: MatchView } }
  | { type: "funnel"; funnel: Funnel }
  | { type: "history"; messages: Anthropic.MessageParam[] }
  | { type: "error"; message: string };

interface ToolOutput {
  forModel: unknown;
  event?: ChatEvent;
}

// Claude directly with ANTHROPIC_API_KEY, or through OpenRouter's Anthropic-compatible API with
// OPENROUTER_API_KEY (same request format, model named "anthropic/...").
const OPENROUTER_KEY = process.env.OPENROUTER_API_KEY;
const MODEL = process.env.CLAUDE_MODEL ?? (OPENROUTER_KEY ? "anthropic/claude-opus-5.5" : "claude-opus-5-5");
const EFFORT = (process.env.CLAUDE_EFFORT ?? "low") as "low" | "medium" | "high";
const MAX_TURNS = 8;

const SYSTEM = `You help a US prediction-market trader with two jobs across Kalshi and Polymarket US:
1. Best venue: they already know the trade; say which venue is cheaper for that size, after fees.
2. Arbitrage: find the same bet priced differently on the two venues, and say whether any gap is still money after fees, rule differences and depth.

How to work:
- Use the tools for every number. Never estimate a price, fee or profit yourself.
- find_matches lists markets Layer matched as the same bet on both venues. Use it to find the market the trader means.
- compare_venues prices one order (side, size) on both venues from their live order books, with each venue's fees and how much it can fill, and names the cheaper one. Use it when the trader names a trade.
- scan_arbitrage runs the arbitrage scan: every match through the same checks (rules differ, no offers, no gap, fees bigger than the gap, too thin, return per day too low). Survivors show gross spread, fees, net and return per day. Translate the trader's words into its filters: "NFL" → search "nfl", "$500" → contracts at the prices involved, "at least 1% a day" → min_return_per_day_pct 1.
- Real gaps after fees are rare. If nothing survives, say so plainly, name the closest one and why it was dropped.
- The app shows each result as a card, so don't repeat every number. Keep the answer under 100 words: one sentence with the answer, then at most three short bullets.
- Compare results that pay back at different times by return per day.
- You can't place orders. If asked, say the "Best venue" and "Arbitrage" tabs have the paper-trade buttons.
- Plain English, short sentences. Dollars as $1.23 and prices as cents (54¢). Never name tools or their settings.
- Never call anything "risk-free" or "best execution". Say "cheaper for this size, after fees, right now".`;

const matchesInput = z.object({
  search: z.string().optional(),
  category: z.string().optional(),
  limit: z.number().int().min(1).max(50).default(10),
});
const compareInput = z.object({
  match_id: z.string(),
  side: z.enum(["yes", "no"]).default("yes"),
  contracts: z.number().int().min(1).max(100_000).default(100),
  max_price_cents: z.number().min(1).max(99).optional(),
});
const scanInput = z.object({
  search: z.string().optional(),
  category: z.string().optional(),
  from_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  to_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
  contracts: z.number().int().min(1).max(100_000).default(100),
  min_edge_cents: z.number().min(0).max(99).default(0),
  min_return_per_day_pct: z.number().min(0).default(0),
  limit: z.number().int().min(1).max(50).default(50),
});

const tools: Anthropic.Tool[] = [
  {
    name: "find_matches",
    description: "List markets Layer matched as the same bet on Kalshi and Polymarket US, with any rule differences.",
    input_schema: {
      type: "object",
      properties: {
        search: { type: "string", description: "Words to search for, e.g. 'nfl', 'chiefs'" },
        category: { type: "string", description: "e.g. sports" },
        limit: { type: "integer", description: "1-50 (default 10)" },
      },
    },
  },
  {
    name: "compare_venues",
    description:
      "Price one buy order on both venues from their live books, with each venue's fees and fillable size, and name the cheaper venue for that size.",
    input_schema: {
      type: "object",
      properties: {
        match_id: { type: "string", description: "The match's id from find_matches or scan_arbitrage" },
        side: { type: "string", enum: ["yes", "no"], description: "The outcome to buy (default yes)" },
        contracts: { type: "integer", description: "Contracts to buy (default 100)" },
        max_price_cents: { type: "number", description: "Never pay more than this a contract, in cents" },
      },
      required: ["match_id"],
    },
  },
  {
    name: "scan_arbitrage",
    description:
      "Scan matched markets for a cross-venue gap and report what happened to each: dropped with a reason, or a survivor with gross spread, fees, net and return per day.",
    input_schema: {
      type: "object",
      properties: {
        search: { type: "string", description: "Words to search for, e.g. 'nfl'" },
        category: { type: "string", description: "e.g. sports" },
        from_date: { type: "string", description: "Only events on or after this day, YYYY-MM-DD" },
        to_date: { type: "string", description: "Only events on or before this day, YYYY-MM-DD" },
        contracts: { type: "integer", description: "Contracts per leg (default 100)" },
        min_edge_cents: { type: "number", description: "Smallest profit per contract after fees, in cents (default 0)" },
        min_return_per_day_pct: { type: "number", description: "Smallest return per day, in percent (default 0)" },
        limit: { type: "integer", description: "Matches to scan, 1-50 (default 50)" },
      },
    },
  },
];

const STATUS: Record<string, string> = {
  find_matches: "Asking Layer which markets are the same bet",
  compare_venues: "Reading both order books and each venue's fees",
  scan_arbitrage: "Scanning matched markets for a gap after fees",
};

async function findMatches(raw: unknown): Promise<ToolOutput> {
  const a = matchesInput.parse(raw);
  const qs = new URLSearchParams({ limit: String(a.limit) });
  if (a.search) qs.set("q", a.search);
  if (a.category) qs.set("category", a.category);
  const { matches } = await engine<{ matches: MatchView[] }>(`/matches?${qs}`);
  return {
    forModel: matches.map((m) => ({ id: m.id, title: m.title, outcome: m.outcome, when: m.event_time ?? m.event_date, rules_differ: m.caveats })),
    event: { type: "matches", matches },
  };
}

async function compareVenues(raw: unknown): Promise<ToolOutput> {
  const a = compareInput.parse(raw);
  const body = { match_id: a.match_id, side: a.side, size: a.contracts, max_price: a.max_price_cents ? a.max_price_cents / 100 : null };
  const best = await engine<BestResult & { match: MatchView }>("/best/preview", { method: "POST", body });
  const forModel = best.ok
    ? {
        cheaper: best.why?.venue,
        reason: best.why?.reason,
        venues: best.why?.venues.map((v) => ({ venue: v.venue, all_in: v.all_in, avg_price: v.avg_price, fees: v.fees, size_at_limit: v.size_at_limit, skipped: v.skip, detail: v.detail })),
      }
    : { error: best.error };
  return { forModel, event: { type: "best", best } };
}

async function scanArbitrage(raw: unknown): Promise<ToolOutput> {
  const a = scanInput.parse(raw);
  const res = await fetch(`${ENGINE_URL}/arb/scan`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      q: a.search,
      category: a.category,
      from_: a.from_date,
      to: a.to_date,
      limit: a.limit,
      size: a.contracts,
      min_edge: a.min_edge_cents / 100,
      min_return_per_day_pct: a.min_return_per_day_pct,
    }),
  }).catch(() => {
    throw new Error(`The engine isn't running at ${ENGINE_URL}. Start it with npm run dev.`);
  });
  if (!res.ok || !res.body) throw new Error(errorText(await res.json().catch(() => null), res.status));
  const funnel: Funnel = { total: 0, counts: {}, rows: [] };
  for await (const e of ndjson<ScanEvent>(res.body)) {
    if (e.type === "start") funnel.total = e.total;
    if (e.type === "row") funnel.rows.push(e);
    if (e.type === "done") funnel.counts = e.counts;
  }
  const survivors = funnel.rows.filter((r) => r.verdict === "survivor");
  const closest = funnel.rows
    .filter((r) => r.verdict !== "survivor" && r.quote?.edge_at_best != null)
    .sort((x, y) => (y.quote!.edge_at_best ?? -1) - (x.quote!.edge_at_best ?? -1))
    .slice(0, 3);
  const brief = (r: ScanRow) => ({
    id: r.match.id,
    title: `${r.match.title} — ${r.match.outcome ?? ""}`,
    verdict: r.verdict,
    reason: r.reason,
    gross_cents: r.quote?.gross_at_best != null ? +(r.quote.gross_at_best * 100).toFixed(2) : null,
    net_cents: r.quote?.edge_at_best != null ? +(r.quote.edge_at_best * 100).toFixed(2) : null,
    contracts: r.quote?.contracts,
    net_profit: r.quote?.net_profit,
    return_per_day_pct: r.quote?.return_per_day_pct,
  });
  return {
    forModel: { scanned: funnel.total, counts: funnel.counts, survivors: survivors.map(brief), closest_dropped: closest.map(brief) },
    event: { type: "funnel", funnel },
  };
}

const RUN: Record<string, (input: unknown) => Promise<ToolOutput>> = {
  find_matches: findMatches,
  compare_venues: compareVenues,
  scan_arbitrage: scanArbitrage,
};

// Created on first use, so building the app doesn't need a key.
let client: Anthropic | null = null;

export async function* chat(history: Anthropic.MessageParam[]): AsyncGenerator<ChatEvent> {
  const messages = [...history];
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());

  for (let turn = 0; turn < MAX_TURNS; turn++) {
    client ??= OPENROUTER_KEY
      ? new Anthropic({ baseURL: "https://openrouter.ai/api", apiKey: null, authToken: OPENROUTER_KEY })
      : new Anthropic();
    const stream = client.messages.stream({
      model: MODEL,
      max_tokens: 16000,
      output_config: { effort: EFFORT },
      system: [
        { type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } },
        { type: "text", text: `Today is ${today} (US Eastern).` },
      ],
      tools,
      messages,
    });

    // Text streams to the UI as it's written. The loop below re-runs once per tool round.
    const queue: string[] = [];
    stream.on("text", (delta) => queue.push(delta));
    const done = stream.finalMessage();
    while (true) {
      const settled = await Promise.race([done.then(() => true), new Promise((r) => setTimeout(r, 40)).then(() => false)]);
      while (queue.length) yield { type: "text", delta: queue.shift()! };
      if (settled) break;
    }
    const message = await done;
    messages.push({ role: "assistant", content: message.content });

    if (message.stop_reason === "refusal") {
      yield { type: "error", message: "Claude declined that request." };
      break;
    }
    const calls = message.content.filter((b): b is Anthropic.ToolUseBlock => b.type === "tool_use");
    if (message.stop_reason !== "tool_use" || !calls.length) break;

    const results: Anthropic.ToolResultBlockParam[] = [];
    for (const call of calls) {
      yield { type: "status", label: STATUS[call.name] ?? "Working" };
      try {
        const run = RUN[call.name];
        if (!run) throw new Error(`unknown tool ${call.name}`);
        const out = await run(call.input);
        if (out.event) yield out.event;
        results.push({ type: "tool_result", tool_use_id: call.id, content: JSON.stringify(out.forModel) });
      } catch (err) {
        results.push({
          type: "tool_result",
          tool_use_id: call.id,
          is_error: true,
          content: err instanceof Error ? err.message : String(err),
        });
      }
    }
    messages.push({ role: "user", content: results });
  }

  yield { type: "history", messages };
}
