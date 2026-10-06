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
  // Layer flagged a rule difference, as one sentence to show with the match, e.g. "Rules differ slightly
  // on where the result comes from. Both pay the same in normal cases, but ..." null when none.
  rule_warning: string | null;
  // Why, in Layer's words: one sentence per rule difference, e.g. "Kalshi settles on the league's
  // official box score; Polymarket US uses ESPN." Empty when Layer sent none: rule_warning stands alone.
  rule_reasons?: string[];
  // The same for every outcome of one game or event: group search results by it.
  event_key: string | null;
  kalshi: MarketView;
  polymarket_us: MarketView;
}

export interface EngineError {
  code: string;
  message: string; // one plain sentence, e.g. "Polymarket US is busy right now. Try again in a few seconds."
  hint: string | null;
  venue: string | null;
  unavailable?: boolean; // the venue didn't answer (busy, down): trying again can work
  detail?: string | null; // the SDK's own words, for logs and the chat's model; never shown
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
  error_line?: string; // why the comparison couldn't run, as one plain sentence
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
  note: string; // "Layer is 95% sure these are the same bet." (+ the rule warning, if any)
  confidence: number | null;
  rule_warning: string | null;
  rule_reasons?: string[]; // as on MatchView
}

export interface VenueRow {
  venue: Venue;
  venue_name: string;
  market: string;
  ok: boolean;
  cheaper: boolean;
  skip: string | null;
  skip_reason: string | null; // one sentence: "Polymarket US's cheapest offer is 98¢, above your 97¢ limit."
  skip_line: string | null; // the same sentence (Every market's name for it)
  unavailable: boolean; // the venue didn't answer (busy, down, a book too old): its price isn't known
  price: number | null; // best ask for the side bought, in dollars
  price_label: string | null; // "54¢"
  chance_label: string | null; // "54%": the chance the market gives that side
  avg_price: number | null;
  avg_price_label: string | null;
  limit_price: number | null;
  fees: number | null;
  // Whole contracts on offer at or under the price it would pay; when it can't fill the order, within its cap.
  fillable: number | null;
  cap_label: string | null; // "39¢": the most it would pay (the SDK's price collar or your limit)
  total_cost: number | null; // cost + fees for the whole order
  total_cost_per_contract: number | null;
  cost_line: string | null; // "100 YES at 22¢ + $1.21 fee = $23.21": price paid + fee = total (null when it can't fill)
  // A dollar amount (spend): each venue at its own size, the most whole contracts the amount buys there.
  contracts?: number | null;
  payout?: number | null; // dollars back if you're right: $1 a contract
  win_line?: string | null; // "Wins $92"
  depth_limited?: boolean; // it ran out of contracts for sale before the money ran out
}

export interface CompareView {
  action: "buy" | "sell";
  side: "yes" | "no";
  size: number | null; // null for a dollar amount: each venue then has its own size (VenueRow.contracts)
  spend?: number | null; // the dollar amount compared, or null for a contract count
  spend_label?: string; // "$50"
  pick_label?: string | null; // the chosen venue's pill for a dollar amount: "Pays more" or "Cheaper"
  headline?: { title: string; detail: string | null; retry: boolean }; // the engine's answer for a dollar amount
  max_price: number | null;
  pair: PairView;
  venues: VenueRow[];
  cheaper: Venue | null;
  cheaper_name: string | null;
  // Venues that didn't answer, by name. Not empty: there's no comparison yet (cheaper is null), only "try again".
  unavailable: string[];
  saving: number | null; // dollars, for this size, vs the other venue
  saving_label: string | null; // "$0.97"
  verdict: string; // "Kalshi is $0.97 cheaper for 100 contracts, fees included: $59.71 vs $60.68."
  try_size: number | null; // neither venue could fill it: a size that gets an answer ("Compare 40 instead")
  collar_note: string | null; // why a thin market can't fill a big order, when the price collar stopped it
  as_of: string;
}

// Best venue for every market (POST /best/scan, engine/spread_engine/every_market.py): one row per
// market, compared on both venues as each finishes.
export type EveryOutcome = "kalshi" | "polymarket_us" | "same" | "one_venue" | "neither" | "error";

export interface EveryRow {
  type: "row";
  match: MatchView;
  order: { match_id: string; side: "yes" | "no"; size: number; max_price: number | null };
  best: BestResult; // the same result /best/preview gives, with its compare view
  outcome: EveryOutcome;
}

export type EveryEvent =
  | { type: "start"; total: number; category: string; size: number; side: string; empty: string | null }
  | EveryRow
  | { type: "done"; total: number; counts: Record<EveryOutcome, number> };

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
  size: number | null; // contracts, or
  spend?: number | null; // dollars: Best venue's Amount box (engine/spread_engine/spend.py)
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

// Save prices: one matched pair's books recorded by the engine (the SDK's record_stream), for Replay.
export interface RecordGame extends MatchView {
  on_now: boolean; // started, by the venues' own start time, and not over
}

export interface Recording {
  state: "recording" | "done" | "stopped" | "failed";
  match: MatchView;
  minutes: number;
  started_at: string;
  ends_at: string;
  seconds_left: number;
  events: number; // book changes and trades written so far
  path: string | null; // null when nothing was saved
  file: string | null;
  error: string | null; // one plain sentence when it failed
}

// Replay: a pair the user recorded with the SDK (Save prices, or npm run record), run through the same scan.
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
  rule_reasons?: string[]; // as on MatchView
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
