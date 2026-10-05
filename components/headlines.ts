// Best venue's one-line answers. Display only: every number and label comes from the engine (the
// uselayer SDK, named in engine/spread_engine/views.py); these functions pick and word them, they
// never compute a price or a fee.

import type { CompareView, VenueRow } from "@/lib/engine";
import { count, money, side } from "./format";

export interface Headline {
  title: string;
  detail: string;
}

const sentence = (s: string) => (/[.!?]$/.test(s) ? s : `${s}.`);

/** Why a venue can't take the order, e.g. "Kalshi: market closed." */
export function skipLine(v: VenueRow): string {
  return sentence(`${v.venue_name}: ${v.skip_reason ?? "can't fill it"}`);
}

/**
 * Where to buy and why: "Buy on Polymarket US: $1.80 cheaper for 100 YES, after fees".
 * `reasonCode` is the SDK's (BestResult.why.reason_code): it says when both venues cost the same.
 */
export function bestHeadline(c: CompareView, reasonCode?: string | null): Headline {
  const order = `${count(c.size)} ${side(c.side)}`;
  const skipped = c.venues.filter((v) => !v.ok).map(skipLine).join(" ");
  const chosen = c.venues.find((v) => v.cheaper);
  if (!chosen || !c.cheaper_name)
    return { title: `No trade: neither venue can fill ${order} right now`, detail: skipped || c.verdict };
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
  const by = c.saving != null && c.saving < 0.005 ? "less than 1¢" : (c.saving_label ?? money(c.saving));
  return {
    title: `Buy on ${name}: ${by} cheaper for ${order}, after fees`,
    detail: `${money(chosen.total_cost)} vs ${money(other.total_cost)} on ${other.venue_name}, fees included.`,
  };
}

/** Layer's match note without the rule warning the engine appends to it (that one is shown on its own). */
export function matchNote(note: string, ruleWarning: string | null): string {
  return ruleWarning ? note.replace(ruleWarning, "").trim() : note;
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

/** "There's already a momentum.py. Replace it, or pick another name." → offer Replace. */
export const alreadyExists = (detail: string) => /^There's already a /.test(detail);
