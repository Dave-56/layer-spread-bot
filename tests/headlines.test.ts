import { describe, expect, it } from "vitest";
import { alreadyExists, bestHeadline, matchNote, strategyNoTrade } from "@/components/headlines";
import type { CompareView, VenueRow } from "@/lib/engine";

const row = (v: Partial<VenueRow>): VenueRow => ({
  venue: "kalshi",
  venue_name: "Kalshi",
  market: "M",
  ok: true,
  cheaper: false,
  skip: null,
  skip_reason: null,
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
      cmp({ venues: [kalshi({ ok: false, skip: "market_closed", skip_reason: "market closed", total_cost: null }), pm({ cheaper: true, total_cost: 1.07 })] }),
    );
    expect(h.title).toBe("Buy on Polymarket US: the only venue that can fill 100 YES");
    expect(h.detail).toBe("$1.07, fees included. Kalshi: market closed.");
  });
  it("says no trade when neither venue can fill, without doubling a full stop", () => {
    const h = bestHeadline(
      cmp({
        cheaper: null,
        cheaper_name: null,
        side: "no",
        venues: [
          kalshi({ ok: false, skip_reason: "best price above your max. The best ask is 0.98, above max_price 0.97." }),
          pm({ ok: false, skip_reason: "nobody selling" }),
        ],
      }),
    );
    expect(h.title).toBe("No trade: neither venue can fill 100 NO right now");
    expect(h.detail).toBe("Kalshi: best price above your max. The best ask is 0.98, above max_price 0.97. Polymarket US: nobody selling.");
  });
  it("words a tie and a tiny saving plainly", () => {
    expect(bestHeadline(cmp({}), "tie_first_listed").title).toBe("Buy on Polymarket US: same price on both venues for 100 YES");
    expect(bestHeadline(cmp({ saving: 0.002, saving_label: "$0.00" })).title).toBe(
      "Buy on Polymarket US: less than 1¢ cheaper for 100 YES, after fees",
    );
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
