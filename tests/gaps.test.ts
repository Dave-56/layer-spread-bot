import { describe, expect, it } from "vitest";
import { lasted, replayHeadline, scanHeadline, tradeLine } from "@/components/gaps";
import type { QuoteView, ScanRow, TradeResult, Verdict } from "@/lib/engine";

const rows = (spec: Partial<Record<Verdict, number>>): ScanRow[] =>
  Object.entries(spec).flatMap(([v, n]) =>
    Array.from({ length: n ?? 0 }, (_, i) => ({ type: "row", verdict: v as Verdict, reason: null, quote: null, match: { id: `${v}${i}` } }) as unknown as ScanRow),
  );

describe("scanHeadline", () => {
  it("leads with how many gaps are still money", () => {
    expect(scanHeadline({ rows: rows({ survivor: 2, no_gap: 48 }) })).toBe("2 of 50 gaps are still money after fees");
    expect(scanHeadline({ rows: rows({ survivor: 1, fees: 3 }) })).toBe("1 of 4 gaps is still money after fees");
  });
  it("says why there are none in one sentence, largest reason first", () => {
    expect(scanHeadline({ rows: rows({ no_gap: 50 }) })).toBe("No trade: all 50 have no gap.");
    expect(scanHeadline({ rows: rows({ fees: 3, no_gap: 46, no_offers: 1 }) })).toBe(
      "No trade: 46 of 50 have no gap, 3 lose the gap to fees and 1 has nobody selling on one venue.",
    );
    expect(scanHeadline({ rows: rows({ no_gap: 5, fees: 2, too_thin: 1, unpriced: 1, per_day_low: 1 }) })).toBe(
      "No trade: 5 of 10 have no gap, 2 lose the gap to fees, 1 couldn't be priced and 2 for other reasons.",
    );
  });
  it("says when nothing was there to check", () => {
    expect(scanHeadline({ rows: [], finishedSkipped: 139 })).toBe("No trade: all 139 matched events are already over.");
    expect(scanHeadline({ rows: [], searched: true })).toBe("No trade: no market on both venues matches that search.");
  });
});

describe("replay", () => {
  const counts = (c: Partial<Record<Verdict, number>>) => ({ unpriced: 0, no_offers: 0, no_gap: 0, fees: 0, below_min_edge: 0, too_thin: 0, no_payout_date: 0, per_day_low: 0, survivor: 0, ...c });
  it("leads with the moments that were money, or why none was", () => {
    expect(replayHeadline({ moments: 62, counts: counts({ survivor: 2, no_gap: 60 }) })).toBe("2 of 62 moments were still money after fees");
    expect(replayHeadline({ moments: 62, counts: counts({ no_gap: 60, fees: 2 }) })).toBe("No trade at any of 62 moments: 60 of 62 had no gap and 2 lost the gap to fees.");
    expect(replayHeadline({ moments: 3, counts: counts({ below_min_edge: 3 }) })).toBe("No trade at any of 3 moments: all 3 were under your minimum.");
  });
  it("says how long the gap lasted", () => {
    expect(lasted({ longest_survivor_s: 120, survivor_seconds: 160 })).toBe("The gap lasted 2.0 min at its longest (2.7 min in all).");
    expect(lasted({ longest_survivor_s: 40, survivor_seconds: 40 })).toBe("The gap lasted 40 s.");
  });
});

describe("tradeLine", () => {
  const q = {
    a: { venue: "kalshi", venue_name: "Kalshi", side: "yes" },
    b: { venue: "polymarket_us", venue_name: "Polymarket US", side: "no" },
  } as unknown as QuoteView;
  const t = (x: Partial<TradeResult>): TradeResult => ({ mode: "paper", status: "hedged", hedged: 100, locked_in: 2.45, unwind_loss: 0, notes: [], quote: q, rule_warning: null, ...x });
  it("says what was bought on each venue, and what's locked in", () => {
    expect(tradeLine(t({}))).toBe("Paper trade: bought 100 YES on Kalshi and NO on Polymarket US. $2.45 locked in after fees.");
  });
  it("says plainly when nothing was bought", () => {
    expect(tradeLine(t({ status: "missed", hedged: 0 }))).toBe("No trade: the gap closed before the orders, so nothing was bought.");
  });
});
