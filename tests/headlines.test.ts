import { describe, expect, it } from "vitest";
import { skipText } from "@/components/format";
import { alreadyExists, bestHeadline, DEFAULT_HOW, everyCell, everyOrder, everySummary, HOW, matchNote, strategyNoTrade } from "@/components/headlines";
import type { BestResult, CompareView, EveryOutcome, EveryRow, VenueRow } from "@/lib/engine";

const row = (v: Partial<VenueRow>): VenueRow => ({
  venue: "kalshi",
  venue_name: "Kalshi",
  market: "M",
  ok: true,
  cheaper: false,
  skip: null,
  skip_reason: null,
  unavailable: false,
  skip_line: null,
  price: 0.54,
  price_label: "54¢",
  chance_label: "54%",
  avg_price: 0.54,
  avg_price_label: "54¢",
  limit_price: 0.56,
  fees: 1,
  fillable: 500,
  cap_label: "59¢",
  total_cost: 54.4,
  total_cost_per_contract: 0.544,
  cost_line: null,
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
    note: "Layer is 95% sure these are the same bet.",
    confidence: 0.95,
    rule_warning: null,
  },
  venues: [kalshi({ total_cost: 54.4 }), pm({ cheaper: true, total_cost: 52.6 })],
  cheaper: "polymarket_us",
  cheaper_name: "Polymarket US",
  unavailable: [],
  saving: 1.8,
  saving_label: "$1.80",
  verdict: "Polymarket US is $1.80 cheaper for 100 contracts, fees included: $52.60 vs $54.40.",
  try_size: null,
  collar_note: null,
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
          kalshi({ ok: false, skip: "market_closed", skip_reason: "This market is closed on Kalshi.", total_cost: null }),
          pm({ cheaper: true, total_cost: 1.07 }),
        ],
      }),
    );
    expect(h.title).toBe("Buy on Polymarket US: the only venue that can fill 100 YES");
    expect(h.detail).toBe("$1.07, fees included. This market is closed on Kalshi.");
    expect(h.retry).toBeUndefined();
  });
  it("says no trade when neither venue can fill, in the engine's plain sentences, never its settings", () => {
    const h = bestHeadline(
      cmp({
        cheaper: null,
        cheaper_name: null,
        side: "no",
        venues: [
          kalshi({ ok: false, skip_reason: "Kalshi's cheapest offer is 98¢, above your 97¢ limit." }),
          pm({ ok: false, skip_reason: "Nobody is selling NO on Polymarket US right now." }),
        ],
      }),
    );
    expect(h.title).toBe("No trade: neither venue can fill 100 NO right now");
    expect(h.detail).toBe("Kalshi's cheapest offer is 98¢, above your 97¢ limit. Nobody is selling NO on Polymarket US right now.");
  });
  it("says why a thin market can't fill a big order, after the venues' sentences", () => {
    const h = bestHeadline(
      cmp({
        cheaper: null,
        cheaper_name: null,
        try_size: 15,
        collar_note: "Spread pays at most 5¢ above a venue's cheapest offer, so a thin market can't fill a big order.",
        venues: [
          kalshi({ ok: false, skip_reason: "Kalshi has only 40 YES for sale at 39¢ or less." }),
          pm({ ok: false, skip_reason: "Polymarket US has only 15 YES for sale at 36¢ or less." }),
        ],
      }),
    );
    expect(h.title).toBe("No trade: neither venue can fill 100 YES right now");
    expect(h.detail).toBe(
      "Kalshi has only 40 YES for sale at 39¢ or less. Polymarket US has only 15 YES for sale at 36¢ or less. " +
        "Spread pays at most 5¢ above a venue's cheapest offer, so a thin market can't fill a big order.",
    );
  });
  it("never calls the other venue the only one when a venue didn't answer", () => {
    // The owner's case: Kalshi priced it, Polymarket US said "too many requests".
    const h = bestHeadline(
      cmp({
        cheaper: null,
        cheaper_name: null,
        saving: null,
        saving_label: null,
        unavailable: ["Polymarket US"],
        verdict: "Couldn't get Polymarket US's price just now, so we can't compare yet.",
        venues: [
          kalshi({ total_cost: 33.53 }),
          pm({ ok: false, skip: "unavailable", unavailable: true, skip_reason: "Polymarket US is busy right now. Try again in a few seconds.", total_cost: null }),
        ],
      }),
      "only_venue",
    );
    expect(h).toEqual({
      title: "Couldn't get Polymarket US's price just now, so we can't compare yet.",
      detail: "Polymarket US is busy right now. Try again in a few seconds.",
      retry: true,
    });
    expect(`${h.title} ${h.detail}`).not.toMatch(/only venue|Buy on|too many requests|polymarket_us/);
  });
  it("words a tie and a tiny saving plainly", () => {
    expect(bestHeadline(cmp({}), "tie_first_listed").title).toBe("Buy on Polymarket US: same price on both venues for 100 YES");
    expect(bestHeadline(cmp({ saving: 0.002, saving_label: "$0.00" })).title).toBe(
      "Buy on Polymarket US: less than 1¢ cheaper for 100 YES, after fees",
    );
  });
});

describe("Best venue's ways in", () => {
  it("opens on Search a game, with Every market second and no strategy tab", () => {
    expect(DEFAULT_HOW).toBe("manual");
    expect(HOW.map((h) => h.label)).toEqual(["Search a game", "Every market"]);
  });
});

describe("skipText", () => {
  it("words every skip code as one sentence with the venue's name, never the SDK's words", () => {
    const codes = ["switched_off", "no_key", "not_allowed", "not_found", "market_closed", "no_book", "stale_book", "no_offers", "above_max_price", "below_min_price", "not_enough_size", "invalid_order", "not_held", "unavailable"];
    for (const code of codes) {
      const s = skipText(code, "Polymarket US");
      expect(s).toMatch(/Polymarket US/);
      expect(s).toMatch(/\.$/);
      expect(s).not.toMatch(/_|max_price|polymarket_us/);
    }
    expect(skipText("unavailable", "Polymarket US")).toBe("Polymarket US didn't answer just now. Try again in a few seconds.");
    expect(skipText("something_new", "Kalshi")).toBe("Kalshi can't take this order.");
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
    const failed = every("error", null, { error_line: "Polymarket US is busy right now. Try again in a few seconds." });
    expect(everyCell(failed)).toEqual({ title: "Couldn't check", detail: "Polymarket US is busy right now. Try again in a few seconds." });
  });
  it("says Couldn't check, not Only Kalshi, when Polymarket US didn't answer", () => {
    const busy = every("error", {
      cheaper: null,
      cheaper_name: null,
      unavailable: ["Polymarket US"],
      venues: [kalshi({}), pm({ ok: false, skip: "unavailable", unavailable: true, skip_reason: "Polymarket US is busy right now. Try again in a few seconds." })],
    });
    expect(everyCell(busy)).toEqual({ title: "Couldn't check", detail: "Polymarket US is busy right now. Try again in a few seconds." });
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
    const w = "Rules differ slightly on where the result comes from. Both pay the same in normal cases, but in a rare case one could pay and the other not.";
    expect(matchNote(`Layer is 95% sure these are the same bet. ${w}`, w)).toBe("Layer is 95% sure these are the same bet.");
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
