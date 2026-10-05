// Best venue's one-line answers. Display only: every number comes from the engine (the uselayer
// SDK); these functions pick and word them, they never compute a price or a fee.

import { VENUE_NAME, type BestVenue as Why, type VenueCost } from "@/lib/engine";
import { count, money, side, SKIP } from "./format";

export interface Headline {
  title: string;
  detail: string;
}

const venueName = (v: string) => VENUE_NAME[v] ?? v;

/** Why a venue can't take the order, e.g. "Kalshi: market closed." */
export function skipLine(v: VenueCost): string {
  return `${venueName(v.venue)}: ${SKIP[v.skip ?? ""] ?? v.skip ?? "can't fill it"}.`;
}

/** Where to buy and why, from the SDK's comparison: "Buy on Polymarket US: $1.80 cheaper for 100 YES, after fees". */
export function bestHeadline(why: Why): Headline {
  const order = `${count(why.size)} ${side(why.side)}`;
  const skipped = why.venues.filter((v) => !v.ok).map(skipLine).join(" ");
  const chosen = why.venues.find((v) => v.venue === why.venue);
  if (!chosen) return { title: `No trade: neither venue can fill ${order} right now`, detail: skipped || why.reason };
  const name = venueName(chosen.venue);
  const other = why.venues.find((v) => v.venue !== why.venue && v.ok);
  if (!other)
    return {
      title: `Buy on ${name}: the only venue that can fill ${order}`,
      detail: `${money(chosen.all_in)}, fees included. ${skipped}`.trim(),
    };
  if (why.reason_code === "tie_more_size")
    return {
      title: `Buy on ${name}: same price on both venues for ${order}`,
      detail: `${money(chosen.all_in)} on each, fees included. ${name} has more for sale.`,
    };
  if (why.reason_code === "tie_first_listed")
    return { title: `Buy on ${name}: same price on both venues for ${order}`, detail: `${money(chosen.all_in)} on each, fees included.` };
  const by = why.saving != null && why.saving < 0.005 ? "less than 1¢" : money(why.saving);
  return {
    title: `Buy on ${name}: ${by} cheaper for ${order}, after fees`,
    detail: `${money(chosen.all_in)} vs ${money(other.all_in)} on ${venueName(other.venue)}, fees included.`,
  };
}

/** Why a strategy made no trade, in one plain sentence. */
export function strategyNoTrade(
  r: { started?: number; looked?: { reason: string }[] },
  s: { example?: boolean; category?: string | null } | undefined,
  searched = false,
): string {
  const started = r.started ?? 0;
  const looked = r.looked ?? [];
  if (!looked.length && started) return `All ${count(started)} games had already started, so there's nothing to buy.`;
  if (!looked.length) {
    if (searched) return "No matched markets for that search.";
    if (s?.category) return `No ${s.category.toLowerCase()} market is open right now, so this template has nothing to buy.`;
    return "No matched markets are open right now.";
  }
  const worded = looked.filter((m) => m.reason === "rules differ").length;
  if (worded === looked.length) return `Kalshi and Polymarket US word all ${worded} of these bets differently.`;
  return `Nothing fit ${s?.example ? "this template's" : "your strategy's"} rules. Compare one below yourself.`;
}

/** A price in dollars as the chance the market gives it: 0.54 → "54%". Display only. */
export function chance(p: number | null | undefined): string {
  if (p == null) return "—";
  const x = p * 100;
  if (x > 0 && x < 1) return "<1%";
  if (x < 100 && x > 99) return ">99%";
  return `${Math.round(x)}%`;
}
