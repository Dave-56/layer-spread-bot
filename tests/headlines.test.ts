import { describe, expect, it } from "vitest";
import { bestHeadline, chance, strategyNoTrade } from "@/components/headlines";
import type { BestVenue, VenueCost } from "@/lib/engine";

const venue = (v: Partial<VenueCost>): VenueCost => ({
  venue: "kalshi",
  market: "M",
  side: "yes",
  size: 100,
  skip: null,
  detail: null,
  best_price: 0.5,
  limit_price: 0.52,
  avg_price: 0.5,
  cost: 50,
  fees: 1,
  all_in: 51,
  all_in_per_contract: 0.51,
  size_at_limit: 500,
  capped_by: null,
  ok: true,
  ...v,
});

const why = (w: Partial<BestVenue>): BestVenue => ({
  action: "buy",
  side: "yes",
  size: 100,
  venue: "polymarket_us",
  reason_code: "cheaper",
  reason: "",
  saving: 1.8,
  venues: [venue({ venue: "kalshi", all_in: 54.4 }), venue({ venue: "polymarket_us", all_in: 52.6 })],
  as_of: "",
  ...w,
});

describe("bestHeadline", () => {
  it("leads with where to buy and the saving the SDK reported", () => {
    expect(bestHeadline(why({}))).toEqual({
      title: "Buy on Polymarket US: $1.80 cheaper for 100 YES, after fees",
      detail: "$52.60 vs $54.40 on Kalshi, fees included.",
    });
  });
  it("says when only one venue can fill, and why the other can't", () => {
    const h = bestHeadline(
      why({ venues: [venue({ venue: "kalshi", ok: false, skip: "market_closed", all_in: null }), venue({ venue: "polymarket_us", all_in: 1.07 })] }),
    );
    expect(h.title).toBe("Buy on Polymarket US: the only venue that can fill 100 YES");
    expect(h.detail).toBe("$1.07, fees included. Kalshi: market closed.");
  });
  it("says no trade when neither venue can fill", () => {
    const h = bestHeadline(
      why({ venue: null, venues: [venue({ venue: "kalshi", ok: false, skip: "no_offers" }), venue({ venue: "polymarket_us", ok: false, skip: "no_book" })] }),
    );
    expect(h.title).toBe("No trade: neither venue can fill 100 YES right now");
    expect(h.detail).toBe("Kalshi: nobody selling. Polymarket US: no book.");
  });
  it("words a tiny saving plainly", () => {
    expect(bestHeadline(why({ saving: 0.002 })).title).toBe("Buy on Polymarket US: less than 1¢ cheaper for 100 YES, after fees");
  });
});

describe("strategyNoTrade", () => {
  it("names the template's category when nothing is open", () => {
    expect(strategyNoTrade({ looked: [] }, { category: "Sports" })).toBe(
      "No sports market is open right now, so this template has nothing to buy.",
    );
  });
  it("blames the search when there was one", () => {
    expect(strategyNoTrade({ looked: [] }, { category: "Sports" }, true)).toBe("No matched markets for that search.");
  });
  it("says when every game had started", () => {
    expect(strategyNoTrade({ looked: [], started: 12 }, undefined)).toBe("All 12 games had already started, so there's nothing to buy.");
  });
});

describe("chance", () => {
  it("shows a price as a chance", () => {
    expect(chance(0.54)).toBe("54%");
    expect(chance(0.004)).toBe("<1%");
    expect(chance(0.995)).toBe(">99%");
    expect(chance(null)).toBe("—");
  });
});
