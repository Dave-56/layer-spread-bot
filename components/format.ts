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

// Layer's rule-difference codes, in words.
export const CAVEAT: Record<string, string> = {
  source_differs: "different data source",
  timing_differs: "different deadline or timing",
  rounding_differs: "different rounding",
  carveout_differs: "different special exceptions",
  definition_differs: "a term is defined differently",
};

export const SKIP: Record<string, string> = {
  switched_off: "venue switched off in this release",
  no_key: "no key for this venue",
  not_allowed: "not allowed by your rules",
  not_found: "market not found",
  market_closed: "market closed",
  no_book: "no book",
  stale_book: "book too old",
  no_offers: "nobody selling",
  above_max_price: "best price above your max",
  below_min_price: "best price below your min",
  not_enough_size: "not enough size within the limit",
  invalid_order: "breaks the market's tick or minimum",
  not_held: "you don't hold it here",
  unavailable: "venue didn't answer",
};
