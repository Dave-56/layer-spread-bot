// Display only. Every number comes from the engine (the uselayer SDK); nothing is computed here.

export const money = (x: number | null | undefined) =>
  x == null ? "—" : `${x < 0 ? "−" : ""}$${Math.abs(x).toFixed(2)}`;

export const cents = (p: number | null | undefined) => {
  if (p == null) return "—";
  const c = p * 100;
  const s = Number.isInteger(Math.round(c * 10) / 10) ? Math.round(c).toString() : c.toFixed(1);
  return `${c < 0 ? "−" : ""}${s.replace("-", "")}¢`;
};

export const pct = (x: number | null | undefined, digits = 2) => (x == null ? "—" : `${x.toFixed(digits)}%`);

export const count = (n: number | null | undefined) =>
  n == null ? "—" : n % 1 === 0 ? n.toLocaleString("en-US") : n.toLocaleString("en-US", { maximumFractionDigits: 2 });

export const side = (s: string) => s.toUpperCase();

export function when(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
    timeZoneName: "short",
  });
}

// The SDK's skip codes (uselayer.best) as one sentence each, for a comparison the engine didn't word.
// The engine's own sentences (views.py) come first wherever they're there.
const SKIP: Record<string, (n: string) => string> = {
  switched_off: (n) => `This release doesn't trade on ${n}.`,
  no_key: (n) => `Add your ${n} key to .env to price it here.`,
  not_allowed: (n) => `Your rules don't allow this order on ${n}.`,
  not_found: (n) => `${n} doesn't know this market.`,
  market_closed: (n) => `This market is closed on ${n}.`,
  no_book: (n) => `There's no book for this market on ${n}.`,
  stale_book: (n) => `${n}'s prices are too old to use right now. Try again in a few seconds.`,
  no_offers: (n) => `Nobody is selling on ${n} right now.`,
  above_max_price: (n) => `${n}'s cheapest offer is above your limit.`,
  below_min_price: (n) => `${n}'s best bid is below your minimum.`,
  not_enough_size: (n) => `${n} doesn't have enough for sale within your limit.`,
  invalid_order: (n) => `This order breaks ${n}'s price step or minimum size.`,
  not_held: (n) => `You don't hold enough of this on ${n} to sell it.`,
  unavailable: (n) => `${n} didn't answer just now. Try again in a few seconds.`,
};

/** Why ``venue`` can't take the order, as one plain sentence. Never the SDK's own words. */
export const skipText = (code: string, venue: string) => (SKIP[code] ?? ((n: string) => `${n} can't take this order.`))(venue);

/** Skip codes that mean the venue didn't answer (its price isn't known), not that it can't fill. */
export const UNKNOWN_SKIPS = new Set(["unavailable", "stale_book"]);
