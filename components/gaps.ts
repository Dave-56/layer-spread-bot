// Arbitrage's one-line answers. Display only: every number and reason comes from the engine (the
// uselayer SDK's quote() and trade(), named in engine/spread_engine/funnel.py); these functions pick
// and word them, they never compute a price or a fee.

import type { QuoteView, ReplayResult, ScanRow, TradeResult, Verdict } from "@/lib/engine";
import { count, money, side } from "./format";

export const DROPS: Exclude<Verdict, "survivor">[] = [
  "unpriced",
  "no_offers",
  "no_gap",
  "fees",
  "below_min_edge",
  "too_thin",
  "no_payout_date",
  "per_day_low",
];

// What n markets (or, in the past tense, n moments of a replay) did at each check.
const SAID: Record<Exclude<Verdict, "survivor">, [one: string, many: string, past: string, pastMany?: string]> = {
  unpriced: ["couldn't be priced", "couldn't be priced", "couldn't be priced"],
  no_offers: ["has nobody selling on one venue", "have nobody selling on one venue", "had nobody selling on one venue"],
  no_gap: ["has no gap", "have no gap", "had no gap"],
  fees: ["loses the gap to fees", "lose the gap to fees", "lost the gap to fees"],
  below_min_edge: ["is under your minimum", "are under your minimum", "was under your minimum", "were under your minimum"],
  too_thin: ["has too little for sale", "have too little for sale", "had too little for sale"],
  no_payout_date: ["has no payout date", "have no payout date", "had no payout date"],
  per_day_low: ["pays back too slowly", "pay back too slowly", "paid back too slowly"],
};

export function said(v: Exclude<Verdict, "survivor">, n: number, past = false): string {
  const [one, many, was, were] = SAID[v];
  if (past) return n === 1 ? was : (were ?? was);
  return n === 1 ? one : many;
}

/** "46 of 50 have no gap, 3 lose the gap to fees and 1 has nobody selling on one venue" */
function reasons(counts: Partial<Record<Verdict, number>>, total: number, past: boolean): string {
  const parts = DROPS.map((v) => ({ v, n: counts[v] ?? 0 }))
    .filter((x) => x.n)
    .sort((a, b) => b.n - a.n);
  if (parts.length === 1) return `${total === 1 ? "it" : total === 2 ? "both" : `all ${count(total)}`} ${said(parts[0].v, parts[0].n, past)}`;
  const named = parts.slice(0, 3).map((x, i) => `${count(x.n)}${i === 0 ? ` of ${count(total)}` : ""} ${said(x.v, x.n, past)}`);
  const rest = parts.slice(3).reduce((t, x) => t + x.n, 0);
  if (rest) named.push(`${count(rest)} for other reasons`);
  return `${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}`;
}

export interface ScanSummary {
  rows: ScanRow[];
  finishedSkipped?: number;
  searched?: boolean;
}

/** The scan's answer, first: how many gaps are still money, or one sentence saying why none is. */
export function scanHeadline({ rows, finishedSkipped, searched }: ScanSummary): string {
  const n = rows.length;
  const k = rows.filter((r) => r.verdict === "survivor").length;
  if (k) return `${count(k)} of ${count(n)} gaps ${k === 1 ? "is" : "are"} still money after fees`;
  if (!n) {
    if (finishedSkipped) return `No trade: all ${count(finishedSkipped)} matched events are already over.`;
    return searched ? "No trade: no market on both venues matches that search." : "No trade: no market is open on both venues right now.";
  }
  const counts: Partial<Record<Verdict, number>> = {};
  for (const r of rows) counts[r.verdict] = (counts[r.verdict] ?? 0) + 1;
  return `No trade: ${reasons(counts, n, false)}.`;
}

/** A replay's answer: how many moments were money, or one sentence saying why none was. */
export function replayHeadline(res: Pick<ReplayResult, "moments" | "counts">): string {
  const k = res.counts.survivor ?? 0;
  if (k) return `${count(k)} of ${count(res.moments)} moments ${k === 1 ? "was" : "were"} still money after fees`;
  return `No trade at any of ${count(res.moments)} moments: ${reasons(res.counts, res.moments, true)}.`;
}

export function seconds(s: number): string {
  return s < 90 ? `${s.toFixed(0)} s` : `${(s / 60).toFixed(1)} min`;
}

/** How long a replay's gap lasted, e.g. "The gap lasted 2.0 min at its longest (2.7 min in all)." */
export function lasted(res: Pick<ReplayResult, "longest_survivor_s" | "survivor_seconds">): string {
  if (res.longest_survivor_s <= 0) return "The gap lasted a single moment.";
  if (Math.abs(res.longest_survivor_s - res.survivor_seconds) < 1) return `The gap lasted ${seconds(res.longest_survivor_s)}.`;
  return `The gap lasted ${seconds(res.longest_survivor_s)} at its longest (${seconds(res.survivor_seconds)} in all).`;
}

const legs = (q: QuoteView) => [q.a, q.b].filter((l): l is NonNullable<typeof l> => !!l);

/** What the paper (or live) trade did, in one or two plain sentences. */
export function tradeLine(t: TradeResult): string {
  const both = legs(t.quote)
    .map((l) => `${side(l.side)} on ${l.venue_name}`)
    .join(" and ");
  const done = t.mode === "live" ? "Bought" : "Paper trade: bought";
  if (t.status === "hedged") return `${done} ${count(t.hedged)} ${both}. ${money(t.locked_in)} locked in after fees.`;
  if (t.status === "missed") return "No trade: the gap closed before the orders, so nothing was bought.";
  if (t.status === "unwound")
    return `Only one side filled, so it was sold back${t.unwind_loss ? ` for a ${money(t.unwind_loss)} loss` : ""}. Nothing is held.`;
  return `Only one side filled and it couldn't all be sold back: ${count(t.hedged)} are matched, the rest is held on one venue. See the paper account above.`;
}
