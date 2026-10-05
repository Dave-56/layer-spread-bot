// The local engine (engine/, Python + the uselayer SDK) does every price, fee, quote and order.
// This app only shows what it returns. The browser reaches it through /engine/* (app/engine), and
// the chat's tools call it directly from the server.

export const ENGINE_URL = process.env.ENGINE_URL ?? `http://127.0.0.1:${process.env.ENGINE_PORT ?? 8765}`;

export type Venue = "kalshi" | "polymarket_us";
export const VENUE_NAME: Record<string, string> = { kalshi: "Kalshi", polymarket_us: "Polymarket US" };

export interface MarketView {
  venue: Venue;
  market_id: string;
  url: string | null;
  event: string | null;
  question: string | null;
  outcome: string | null;
  event_time: string | null;
  close_time: string | null;
}

export interface MatchView {
  id: string;
  title: string;
  outcome: string | null;
  category: string | null;
  event_date: string | null;
  event_time: string | null;
  confidence: number | null;
  caveats: string[];
  // Layer flagged a rule difference, as one sentence to show with the match, e.g. "Worded differently:
  // different data source. The two could settle differently." null when none.
  rule_warning: string | null;
  // The same for every outcome of one game or event: group search results by it.
  event_key: string | null;
  kalshi: MarketView;
  polymarket_us: MarketView;
}

export interface EngineError {
  code: string;
  message: string;
  hint: string | null;
  venue: string | null;
}

export interface Status {
  mode: "paper" | "live";
  budget: number;
  keys: { layer: boolean; kalshi: boolean; polymarket_us: boolean };
  sdk_version: string;
  client_error: EngineError | null;
}

// Job 1: one venue's side of the comparison (uselayer.best.VenueCost).
export interface VenueCost {
  venue: Venue;
  market: string;
  side: string;
  size: number;
  skip: string | null;
  detail: string | null;
  best_price: number | null;
  limit_price: number | null;
  avg_price: number | null;
  cost: number | null;
  fees: number | null;
  all_in: number | null;
  all_in_per_contract: number | null;
  size_at_limit: number | null;
  capped_by: string | null;
  ok: boolean;
}

export interface BestVenue {
  action: "buy" | "sell";
  side: string;
  size: number;
  venue: Venue | null;
  reason_code: string;
  reason: string;
  saving: number | null;
  venues: VenueCost[];
  as_of: string;
}

export interface OrderView {
  venue: Venue;
  market: string;
  side: string;
  price: number;
  size: number;
  status: string;
  filled: number;
  avg_price: number | null;
  fees: number;
  mode: string;
}

// What the SDK's guardrails say about the order before it's sent (uselayer Preview).
export interface PreviewView {
  allowed: boolean;
  blocked_by: string | null;
  needs_approval: boolean;
  problems: string[];
  rules: { decision: { result: string; rule: string | null; reason: string | null } };
}

export interface BestResult {
  ok?: boolean;
  error?: EngineError;
  sent?: boolean;
  order?: OrderView | null;
  why?: BestVenue;
  compare?: CompareView;
  preview?: PreviewView | null;
  mode?: string;
}

// Best venue, named and labelled for the screen (engine/spread_engine/views.py compare_view). Every
// number is the SDK's; the labels are the engine's. Show them as they are.
export interface PairView {
  kalshi: { title: string | null; outcome: string | null; question: string | null; ticker: string; url: string | null };
  polymarket_us: { title: string | null; outcome: string | null; question: string | null; slug: string; url: string | null };
  note: string; // "Layer matched these as the same bet (95% confidence)." (+ the rule warning, if any)
  confidence: number | null;
  rule_warning: string | null;
}

export interface VenueRow {
  venue: Venue;
  venue_name: string;
  market: string;
  ok: boolean;
  cheaper: boolean;
  skip: string | null;
  skip_reason: string | null; // one plain clause, e.g. "best price 98¢, above your max of 97¢"
  price: number | null; // best ask for the side bought, in dollars
  price_label: string | null; // "54¢"
  chance_label: string | null; // "54%": the chance the market gives that side
  avg_price: number | null;
  avg_price_label: string | null;
  limit_price: number | null;
  fees: number | null;
  fillable: number | null; // whole contracts on offer at or under the price it would pay
  total_cost: number | null; // cost + fees for the whole order
  total_cost_per_contract: number | null;
}

export interface CompareView {
  action: "buy" | "sell";
  side: "yes" | "no";
  size: number;
  max_price: number | null;
  pair: PairView;
  venues: VenueRow[];
  cheaper: Venue | null;
  cheaper_name: string | null;
  saving: number | null; // dollars, for this size, vs the other venue
  saving_label: string | null; // "$0.97"
  verdict: string; // "Kalshi is $0.97 cheaper for 100 contracts, fees included: $59.71 vs $60.68."
  as_of: string;
}

// A file in engine/spread_engine/strategies/.
export interface StrategyInfo {
  id: string;
  name: string;
  category: string; // one of StrategyList.categories
  description: string;
  example: boolean;
  error: string | null; // the file didn't load: one line why (it can't be run)
}

export interface StrategyList {
  categories: string[]; // "Sports", "Crypto", "News, politics & economics", "Your own"
  strategies: StrategyInfo[];
}

export interface Signal {
  match_id: string;
  side: "yes" | "no";
  size: number;
  max_price: number | null;
  why: string;
  match: MatchView;
}

// Job 2: one leg of a quoted pair, and the quote (uselayer.Quote).
export interface QuoteLeg {
  venue: Venue;
  venue_name: string;
  market: string;
  side: string;
  best_price: number;
  limit_price: number;
  average_price: number | null;
  contracts_at_best: number;
  cost: number;
  fee: number;
}

export interface QuoteView {
  a: QuoteLeg | null;
  b: QuoteLeg | null;
  contracts: number;
  gross_at_best: number | null;
  edge_at_best: number | null;
  gross_spread: number;
  fees: number;
  net_profit: number;
  net_profit_per_contract: number;
  cost: number;
  return_pct: number;
  days_held: number | null;
  return_per_day_pct: number | null;
  settles_at: string | null;
  limited_by: string;
  as_of: string;
}

// A rule difference is not a verdict: those matches go through every check and carry
// match.rule_warning instead.
export type Verdict =
  | "unpriced"
  | "no_offers"
  | "no_gap"
  | "fees"
  | "below_min_edge"
  | "too_thin"
  | "no_payout_date"
  | "per_day_low"
  | "survivor";

export interface ScanRow {
  type: "row";
  match: MatchView;
  verdict: Verdict;
  reason: string | null;
  quote: QuoteView | null;
}

export type ScanEvent =
  | { type: "start"; total: number }
  | ScanRow
  | { type: "done"; total: number; counts: Record<Verdict, number>; finished_skipped?: number }
  | { type: "error"; error: EngineError };

// Replay: a pair the user recorded with the SDK (npm run record), run through the same scan.
export interface ReplayFile {
  path: string;
  file: string;
  bytes?: number;
  events?: number;
  from?: string | null;
  to?: string | null;
  markets?: Record<string, string[]>;
  top_of_book_only?: boolean;
  size_unknown?: boolean;
  match?: MatchView | null;
  error?: string;
}

export interface ReplayMoment extends Omit<ScanRow, "type"> {
  at: string;
}

export interface ReplayResult {
  path: string;
  file: string;
  from: string | null;
  to: string | null;
  top_of_book_only: boolean;
  size_unknown: boolean;
  // Sizes in the file are placeholders: the replay priced this many contracts at the top price, and
  // size_note says so ("Size unknown: assumes 100 contracts at the top price on both venues.").
  assumed_size: number | null;
  size_note: string | null;
  match: MatchView;
  settles_at: string | null;
  moments: number;
  counts: Record<Verdict, number>;
  best: ReplayMoment | null;
  best_survivor: ReplayMoment | null;
  survivor_seconds: number;
  longest_survivor_s: number;
}

export interface TradeResult {
  mode: string;
  status: "hedged" | "missed" | "unwound" | "exposed";
  hedged: number;
  locked_in: number;
  unwind_loss: number;
  notes: string[];
  quote: QuoteView;
  rule_warning: string | null;
}

// Each reason's group name on the Arbitrage screen (components/gaps.ts words the counts).
export const VERDICT_LABEL: Record<Verdict, string> = {
  unpriced: "Couldn't be priced",
  no_offers: "Nobody selling",
  no_gap: "No gap",
  fees: "Fees bigger than the gap",
  below_min_edge: "Under your minimum",
  too_thin: "Too little for sale",
  no_payout_date: "No payout date",
  per_day_low: "Pays back too slowly",
  survivor: "Still money after fees",
};

/** Survivors in the order to show them: worded the same on both venues first, then most profit
 *  after fees. A rule difference doesn't drop a gap, but one that could settle differently ranks
 *  below one that can't. */
export function survivorOrder<R extends { match: MatchView; quote: QuoteView | null }>(rows: R[]): R[] {
  return [...rows].sort(
    (a, b) =>
      Number(!!a.match.rule_warning) - Number(!!b.match.rule_warning) ||
      (b.quote?.net_profit ?? 0) - (a.quote?.net_profit ?? 0),
  );
}

/** Read a newline-delimited JSON stream, one parsed object per line. */
export async function* ndjson<T>(body: ReadableStream<Uint8Array>): AsyncGenerator<T> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) if (line.trim()) yield JSON.parse(line) as T;
  }
  if (buffer.trim()) yield JSON.parse(buffer) as T;
}

/** An engine error as one line for the screen. */
export function errorText(body: unknown, status: number): string {
  const b = body as { error?: EngineError | string; detail?: unknown } | null;
  if (b?.error && typeof b.error === "object") return [b.error.message, b.error.hint].filter(Boolean).join(" ");
  if (typeof b?.error === "string") return b.error;
  if (typeof b?.detail === "string") return b.detail;
  return `The engine answered ${status}. Is it running? (npm run dev starts it.)`;
}

/** Server side: call the engine directly. */
export async function engine<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(ENGINE_URL + path, {
      method: init?.method ?? "GET",
      // The engine refuses a POST without JSON and the proxy header (see lib/guard.ts).
      headers: init?.body === undefined ? { "x-spread-proxy": "1" } : { "content-type": "application/json", "x-spread-proxy": "1" },
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
    });
  } catch {
    throw new Error(`The engine isn't running at ${ENGINE_URL}. Start it with npm run dev.`);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorText(body, res.status));
  return body as T;
}
