import { describe, expect, it } from "vitest";
import { alreadyExists, bestHeadline, everyCell, everyOrder, everySummary, matchNote, strategyNoTrade } from "@/components/headlines";
import type { BestResult, CompareView, EveryOutcome, EveryRow, VenueRow } from "@/lib/engine";

const row = (v: Partial<VenueRow>): VenueRow => ({
  venue: "kalshi",
  venue_name: "Kalshi",
  market: "M",
  ok: true,
  cheaper: false,
  skip: null,
  skip_reason: null,
  skip_line: null,
  price: 0.54,
  price_label: "54¢",
  chance_label: "54%",
  avg_price: 0.54,
  avg_price_label: "54¢",
  limit_price: 0.56,
  fees: 1,
  fillable: 500,
  total_cost: 54.4,
  total_cost_per_contract: 0.544,
  ...v,
});

const kalshi = (v: Partial<VenueRow> = {}) => row({ venue: "kalshi", venue_name: "Kalshi", ...v });
const pm = (v: Partial<VenueRow> = {}) => row({ venue: "polymarket_us", venue_name: "Polymarket US", ...v });

const cmp = (c: Partial<CompareView>): CompareView => ({
  action: "buy",
  side: "yes",
  size: 100,
  max_price: null,
  pair: {
    kalshi: { title: "A vs B", outcome: "A", question: "A wins", ticker: "K", url: null },
    polymarket_us: { title: "A vs B", outcome: "A", question: "Will A win?", slug: "p", url: null },
    note: "Layer matched these as the same bet (95% confidence).",
    confidence: 0.95,
    rule_warning: null,
  },
  venues: [kalshi({ total_cost: 54.4 }), pm({ cheaper: true, total_cost: 52.6 })],
  cheaper: "polymarket_us",
  cheaper_name: "Polymarket US",
  saving: 1.8,
  saving_label: "$1.80",
  verdict: "Polymarket US is $1.80 cheaper for 100 contracts, fees included: $52.60 vs $54.40.",
  as_of: "",
  ...c,
});

describe("bestHeadline", () => {
  it("leads with where to buy and the engine's saving label", () => {
    expect(bestHeadline(cmp({}))).toEqual({
      title: "Buy on Polymarket US: $1.80 cheaper for 100 YES, after fees",
      detail: "$52.60 vs $54.40 on Kalshi, fees included.",
    });
  });
  it("says when only one venue can fill, with the engine's reason for the other", () => {
    const h = bestHeadline(
      cmp({
        venues: [
          kalshi({ ok: false, skip: "market_closed", skip_reason: "market closed", skip_line: "Kalshi isn't taking orders on this market right now.", total_cost: null }),
          pm({ cheaper: true, total_cost: 1.07 }),
        ],
      }),
    );
    expect(h.title).toBe("Buy on Polymarket US: the only venue that can fill 100 YES");
    expect(h.detail).toBe("$1.07, fees included. Kalshi isn't taking orders on this market right now.");
  });
  it("says no trade when neither venue can fill, in the engine's plain sentences, never its settings", () => {
    const h = bestHeadline(
      cmp({
        cheaper: null,
        cheaper_name: null,
        side: "no",
        venues: [
          kalshi({
            ok: false,
            skip_reason: "best price above your max. The best ask is 0.98, above max_price 0.97.",
            skip_line: "Kalshi's cheapest NO costs more than your max price.",
          }),
          pm({ ok: false, skip_reason: "nobody selling", skip_line: "Nobody is selling NO on Polymarket US right now." }),
        ],
      }),
    );
    expect(h.title).toBe("No trade: neither venue can fill 100 NO right now");
    expect(h.detail).toBe("Kalshi's cheapest NO costs more than your max price. Nobody is selling NO on Polymarket US right now.");
    expect(h.detail).not.toMatch(/max_price|0\.9/);
  });
  it("words a tie and a tiny saving plainly", () => {
    expect(bestHeadline(cmp({}), "tie_first_listed").title).toBe("Buy on Polymarket US: same price on both venues for 100 YES");
    expect(bestHeadline(cmp({ saving: 0.002, saving_label: "$0.00" })).title).toBe(
      "Buy on Polymarket US: less than 1¢ cheaper for 100 YES, after fees",
    );
  });
});

const every = (outcome: EveryOutcome, c: Partial<CompareView> | null, best: Partial<BestResult> = {}): EveryRow => ({
  type: "row",
  match: {} as EveryRow["match"],
  order: { match_id: "K", side: "yes", size: 100, max_price: null },
  best: c ? { ok: true, compare: cmp(c), ...best } : { ok: false, ...best },
  outcome,
});

describe("every market", () => {
  it("says who is cheaper and by the engine's saving label", () => {
    expect(everyCell(every("polymarket_us", {}))).toEqual({ title: "Polymarket US", detail: "$1.80 cheaper" });
    expect(everyCell(every("kalshi", { cheaper_name: "Kalshi", saving: 0.004, saving_label: "$0.00" }))).toEqual({ title: "Kalshi", detail: "less than 1¢ cheaper" });
    expect(everyCell(every("same", { saving: 0 }))).toEqual({ title: "Same price", detail: "$52.60 on each" });
  });
  it("says why a venue can't price it, in one plain sentence", () => {
    const one = every("one_venue", {
      venues: [kalshi({ ok: false, skip: "stale_book", skip_line: "Kalshi's prices didn't refresh in time to compare." }), pm({ cheaper: true })],
      saving: null,
    });
    expect(everyCell(one)).toEqual({ title: "Only Polymarket US", detail: "Kalshi's prices didn't refresh in time to compare." });
    const failed = every("error", null, { error_line: "Polymarket US is getting too many requests right now. Try again in a minute." });
    expect(everyCell(failed)).toEqual({ title: "Couldn't check", detail: "Polymarket US is getting too many requests right now. Try again in a minute." });
  });
  it("puts the biggest saving first, then ties, one venue, neither and errors", () => {
    const rows = [
      every("error", null),
      every("one_venue", { saving: null }),
      every("kalshi", { saving: 0.5 }),
      every("same", { saving: 0 }),
      every("polymarket_us", { saving: 3.76 }),
      every("neither", { saving: null }),
    ];
    expect(rows.sort(everyOrder).map((r) => `${r.outcome} ${r.best.compare?.saving ?? ""}`)).toEqual([
      "polymarket_us 3.76",
      "kalshi 0.5",
      "same 0",
      "one_venue ",
      "neither ",
      "error ",
    ]);
  });
  it("sums the scan up in one sentence", () => {
    const counts = { kalshi: 7, polymarket_us: 9, same: 1, one_venue: 5, neither: 2, error: 1 };
    expect(everySummary(counts, 25)).toBe("Checked 25 markets. Kalshi is cheaper on 7, Polymarket US on 9, same price on 1. 8 couldn't be priced on both venues.");
    expect(everySummary({ ...counts, kalshi: 0, same: 0, one_venue: 0, neither: 0, error: 0 }, 9)).toBe("Checked 9 markets. Polymarket US is cheaper on 9.");
    expect(everySummary({ kalshi: 0, polymarket_us: 0, same: 0, one_venue: 3, neither: 1, error: 0 }, 4)).toBe("Checked 4 markets. None could be priced on both venues.");
  });
});

describe("matchNote", () => {
  it("drops the rule warning the engine appends, since it's shown on its own", () => {
    const w = "Worded differently: different data source. The two could settle differently.";
    expect(matchNote(`Layer matched these as the same bet (95% confidence). ${w}`, w)).toBe("Layer matched these as the same bet (95% confidence).");
  });
});

describe("strategyNoTrade", () => {
  it("falls back to one plain sentence", () => {
    expect(strategyNoTrade({ looked: [] }, true)).toBe("No matched markets for that search.");
    expect(strategyNoTrade({ looked: [], started: 12 })).toBe("All 12 games had already started, so there's nothing to buy.");
  });
});

describe("alreadyExists", () => {
  it("spots the engine's name clash sentence", () => {
    expect(alreadyExists("There's already a momentum.py. Replace it, or pick another name.")).toBe(true);
    expect(alreadyExists("momentum.py didn't load. Line 3: invalid syntax.")).toBe(false);
  });
});
