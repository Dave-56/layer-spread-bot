// Best venue's one-line answers. Display only: every number and label comes from the engine (the
// uselayer SDK, named in engine/spread_engine/views.py); these functions pick and word them, they
// never compute a price or a fee.

import type { CompareView, EveryOutcome, EveryRow, VenueRow } from "@/lib/engine";
import { count, money, side } from "./format";

export interface Headline {
  title: string;
  detail: string;
  /** A venue didn't answer: there's no answer yet, only "Try again". */
  retry?: boolean;
}

// Best venue's ways in, in the order shown. The first is the default view.
export const HOW = [
  { id: "manual", label: "Search a game" },
  { id: "every", label: "Every market" },
] as const;
export type How = (typeof HOW)[number]["id"];
export const DEFAULT_HOW: How = HOW[0].id;

const sentence = (s: string) => (/[.!?]$/.test(s) ? s : `${s}.`);

/** Why a venue can't take the order: the engine's plain sentence, e.g. "This market is closed on Kalshi." */
export function skipLine(v: VenueRow): string {
  return sentence(v.skip_line ?? v.skip_reason ?? `${v.venue_name} can't take this order`);
}

/** The engine's saving label, or "less than 1¢" when it rounds to nothing. */
const savingWords = (c: CompareView) => (c.saving != null && c.saving < 0.005 ? "less than 1¢" : (c.saving_label ?? money(c.saving)));

/**
 * Where to buy and why: "Buy on Polymarket US: $1.80 cheaper for 100 YES, after fees".
 * `reasonCode` is the SDK's (BestResult.why.reason_code): it says when both venues cost the same.
 */
export function bestHeadline(c: CompareView, reasonCode?: string | null): Headline {
  const order = `${count(c.size)} ${side(c.side)}`;
  // A venue that didn't answer isn't a venue that can't fill: there's no comparison yet.
  if (c.unavailable?.length)
    return { title: c.verdict, detail: c.venues.filter((v) => v.unavailable).map(skipLine).join(" "), retry: true };
  const skipped = c.venues.filter((v) => !v.ok).map(skipLine).join(" ");
  const chosen = c.venues.find((v) => v.cheaper);
  if (!chosen || !c.cheaper_name)
    return { title: `No trade: neither venue can fill ${order} right now`, detail: [skipped || c.verdict, c.collar_note].filter(Boolean).join(" ") };
  const name = c.cheaper_name;
  const other = c.venues.find((v) => !v.cheaper && v.ok);
  if (!other)
    return {
      title: `Buy on ${name}: the only venue that can fill ${order}`,
      detail: `${money(chosen.total_cost)}, fees included. ${skipped}`.trim(),
    };
  if (reasonCode === "tie_more_size")
    return {
      title: `Buy on ${name}: same price on both venues for ${order}`,
      detail: `${money(chosen.total_cost)} on each, fees included. ${name} has more for sale.`,
    };
  if (reasonCode === "tie_first_listed")
    return { title: `Buy on ${name}: same price on both venues for ${order}`, detail: `${money(chosen.total_cost)} on each, fees included.` };
  return {
    title: `Buy on ${name}: ${savingWords(c)} cheaper for ${order}, after fees`,
    detail: `${money(chosen.total_cost)} vs ${money(other.total_cost)} on ${other.venue_name}, fees included.`,
  };
}

/** Layer's match note without the rule warning the engine appends to it (that one is shown on its own). */
export function matchNote(note: string, ruleWarning: string | null): string {
  return ruleWarning ? note.replace(ruleWarning, "").trim() : note;
}

/** A rule warning with Layer's reasons after it, for a hover title. undefined when the rules match. */
export function ruleTitle(m: { rule_warning: string | null; rule_reasons?: string[] }): string | undefined {
  return m.rule_warning ? [m.rule_warning, ...(m.rule_reasons ?? [])].join(" ") : undefined;
}

/** Why a strategy made no trade, when it didn't say: one plain sentence. */
export function strategyNoTrade(r: { started?: number; looked?: { reason: string }[] }, searched = false): string {
  const started = r.started ?? 0;
  const looked = r.looked ?? [];
  if (!looked.length && started) return `All ${count(started)} games had already started, so there's nothing to buy.`;
  if (!looked.length) return searched ? "No matched markets for that search." : "No matched markets are open right now.";
  const worded = looked.filter((m) => m.reason === "rules differ").length;
  if (worded === looked.length) return `Kalshi and Polymarket US word all ${worded} of these bets differently.`;
  return "Nothing fit this strategy's rules. Compare one below yourself.";
}

// ---- Every market ---------------------------------------------------------------------------------

/** One row's answer, for the "Pays more for $50 on YES" column: who, then by how much or why not. */
export function everyCell(r: EveryRow): Headline {
  const c = r.best.compare;
  if (r.outcome === "error" || !c) {
    // A venue that didn't answer: say which and why, never "only the other venue".
    const why = c?.unavailable?.length ? c.venues.filter((v) => v.unavailable).map(skipLine).join(" ") : null;
    return { title: "Couldn't check", detail: why || r.best.error_line || "Couldn't read the prices for this one." };
  }
  const skipped = c.venues.filter((v) => !v.ok).map(skipLine).join(" ");
  if (c.spend != null) {
    // A dollar amount: who pays more if you win, and by how much.
    if (r.outcome === "kalshi" || r.outcome === "polymarket_us") return { title: c.cheaper_name ?? "", detail: `pays ${c.more_label} more` };
    if (r.outcome === "same") return { title: "Same payout", detail: `${c.venues.find((v) => v.win_line)?.win_line ?? ""} on each`.trim() };
  }
  if (r.outcome === "kalshi" || r.outcome === "polymarket_us") return { title: c.cheaper_name ?? "", detail: `${savingWords(c)} cheaper` };
  if (r.outcome === "same") return { title: "Same price", detail: `${money(c.venues.find((v) => v.cheaper)?.total_cost)} on each` };
  if (r.outcome === "one_venue") return { title: `Only ${c.cheaper_name}`, detail: skipped };
  return { title: "Neither venue", detail: skipped };
}

const RANK: Record<EveryOutcome, number> = { kalshi: 0, polymarket_us: 0, same: 1, one_venue: 2, neither: 3, error: 4 };

/** Biggest saving (or for a dollar amount, biggest extra payout) first; then same price, one venue
 * only, neither, and the ones that couldn't be checked. */
export function everyOrder(a: EveryRow, b: EveryRow): number {
  const gap = (r: EveryRow) => r.best.compare?.more || r.best.compare?.saving || 0;
  return RANK[a.outcome] - RANK[b.outcome] || gap(b) - gap(a);
}

/** The scan in one sentence, from the engine's counts. ``dollars``: it compared a dollar amount. */
export function everySummary(counts: Record<EveryOutcome, number>, total: number, dollars = false): string {
  const parts: string[] = [];
  const wins = dollars ? "pays more" : "is cheaper";
  if (counts.kalshi) parts.push(`Kalshi ${wins} on ${count(counts.kalshi)}`);
  if (counts.polymarket_us) parts.push(`Polymarket US ${parts.length ? "" : `${wins} `}on ${count(counts.polymarket_us)}`);
  if (counts.same) parts.push(`${parts.length ? "same" : "Same"} ${dollars ? "payout" : "price"} on ${count(counts.same)}`);
  const notBoth = counts.one_venue + counts.neither + counts.error;
  if (!parts.length) return `Checked ${count(total)} markets. None could be priced on both venues.`;
  const rest = notBoth ? ` ${count(notBoth)} couldn't be priced on both venues.` : "";
  return `Checked ${count(total)} markets. ${parts.join(", ")}.${rest}`;
}

/** "There's already a momentum.py. Replace it, or pick another name." → offer Replace. */
export const alreadyExists = (detail: string) => /^There's already a /.test(detail);
