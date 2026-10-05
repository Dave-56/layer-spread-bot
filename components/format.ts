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

// The SDK's skip codes in words, the same as the engine's (views.SKIP). Never show the SDK's own
// detail text ("The best ask is 0.98, above max_price 0.97.").
export const SKIP: Record<string, string> = {
  switched_off: "orders here are switched off in this release",
  no_key: "no key for this venue",
  not_allowed: "not allowed by your rules",
  not_found: "market not found",
  market_closed: "market closed",
  no_book: "no prices yet",
  stale_book: "its prices were too old to use; try again in a few seconds",
  no_offers: "nobody selling",
  above_max_price: "best price above your max",
  below_min_price: "best price below your min",
  not_enough_size: "not enough for sale within your max price",
  invalid_order: "breaks the market's price step or minimum",
  not_held: "you don't hold it here",
  unavailable: "the venue didn't answer; try again",
};
