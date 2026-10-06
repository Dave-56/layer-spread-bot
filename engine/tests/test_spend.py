"""Best venue by the dollar (spend.py), on MADE-UP books priced by the real SDK in backtest mode (no network)."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest
from uselayer import Match, VenueError
from uselayer.books import Book

from spread_engine import spend
from spread_engine.views import money_label
from tests.test_app import SECRET, local
from tests.test_replay import MATCH

K, PM = MATCH["kalshi"]["market_id"], MATCH["polymarket_us"]["market_id"]
AT = "2026-10-10T12:00:00Z"


def book(venue: str, market: str, asks: list[tuple[float, float]], bids: list[tuple[float, float]] | None = None) -> Book:
    return Book.model_validate({
        "venue": venue, "market": market, "as_of": AT, "source": "venue",
        "asks": [{"price": p, "size": s} for p, s in asks],
        "bids": [{"price": p, "size": s} for p, s in (bids or [(0.30, 500)])],
    })


def view(amount: float, k_asks: list[tuple[float, float]], pm_asks: list[tuple[float, float]], **kw):  # noqa: ANN003, ANN201
    m = Match.model_validate(MATCH)
    return spend.books_view(m, "yes", amount, [book("kalshi", K, k_asks), book("polymarket_us", PM, pm_asks)], **kw)


def venue(v: dict, name: str) -> dict:
    return next(r for r in v["venues"] if r["venue"] == name)


# --- the search -------------------------------------------------------------------------------------


def fake_pricer(price: float, fee_per_order: float, depth: int):  # noqa: ANN201
    """A venue whose cost is n × price + a fee rounded up to the cent, with ``depth`` contracts for sale."""

    def at(n: int) -> SimpleNamespace:
        ok = n <= depth
        fee = math.ceil(n * fee_per_order * 100) / 100
        row = SimpleNamespace(venue="kalshi", ok=ok, skip=None if ok else "not_enough_size", size=n, best_price=price, all_in=round(n * price + fee, 6) if ok else None)
        return SimpleNamespace(venues=[row])

    return at


@pytest.mark.parametrize("amount", [0.5, 1, 7.77, 50, 99.99, 1000])
def test_the_search_finds_exactly_the_most_that_fits(amount: float) -> None:
    price = fake_pricer(0.41, 0.0172, depth=2000)
    _, best, depth = spend.most_for(price, "kalshi", amount)
    brute = max((n for n in range(1, 2001) if price(n).venues[0].all_in <= amount), default=None)
    assert (best.size if best else None) == brute
    assert depth is (brute == 2000)  # $1,000 would buy more than the 2,000 for sale


def test_the_search_stops_where_the_book_runs_out() -> None:
    _, best, depth = spend.most_for(fake_pricer(0.41, 0.0172, depth=30), "kalshi", 1000)
    assert best.size == 30 and depth is True


# --- the answer, priced by the SDK ----------------------------------------------------------------


def test_more_contracts_pays_more_and_each_fits_the_amount() -> None:
    v = view(50, [(0.45, 5000)], [(0.40, 5000)])
    k, pm = venue(v, "kalshi"), venue(v, "polymarket_us")
    assert pm["contracts"] > k["contracts"] > 0
    assert k["total_cost"] <= 50 and pm["total_cost"] <= 50
    assert v["cheaper"] == "polymarket_us" and pm["cheaper"] and not k["cheaper"]
    more = pm["contracts"] - k["contracts"]
    assert v["headline"]["title"] == f"Buy on Polymarket US: it pays ${more} more if you win"
    assert v["headline"]["detail"] == f"Your $50 wins ${pm['contracts']} on Polymarket US and ${k['contracts']} on Kalshi, fees included."
    assert pm["win_line"] == f"Wins ${pm['contracts']}"
    assert pm["cost_line"].startswith(f"{money_label(pm['total_cost'])} at 40¢ avg, $")


def sdk_cost(books: list[Book], name: str, n: int) -> float | None:
    """What the SDK charges for n contracts on one venue, fees included, against these books."""
    from uselayer import Client

    out: dict[str, float | None] = {}

    def on_book(c, b) -> None:  # noqa: ANN001
        if b.venue == books[-1].venue:
            row = next(v for v in c.preview_best(Match.model_validate(MATCH), "yes", n).why.venues if v.venue == name)
            out["cost"] = row.all_in if row.ok else None

    Client(mode="backtest", books=books, store=":memory:", on_alert=lambda e: None).replay(on_book)
    return out["cost"]


def test_one_more_contract_would_not_fit() -> None:
    books = [book("kalshi", K, [(0.45, 5000)]), book("polymarket_us", PM, [(0.40, 5000)])]
    v = view(50, [(0.45, 5000)], [(0.40, 5000)])
    for name in ("kalshi", "polymarket_us"):
        n = venue(v, name)["contracts"]
        assert sdk_cost(books, name, n) == venue(v, name)["total_cost"] <= 50
        assert sdk_cost(books, name, n + 1) > 50  # one more, with its fee, goes over


def test_same_payout_goes_to_the_cheaper_one() -> None:
    v = view(10, [(0.50, 5000)], [(0.50, 5000)])
    k, pm = venue(v, "kalshi"), venue(v, "polymarket_us")
    assert k["contracts"] == pm["contracts"]
    title = v["headline"]["title"]
    if abs(k["total_cost"] - pm["total_cost"]) < 0.005:
        assert title == f"Same on both: your $10 wins ${k['contracts']} either way"
        assert v["cheaper"] is None and v["pick_label"] is None and not k["cheaper"] and not pm["cheaper"]
    else:
        cheaper = "Kalshi" if k["total_cost"] < pm["total_cost"] else "Polymarket US"
        assert title.startswith(f"Buy on {cheaper}: the same ${k['contracts']} if you win, $")
        assert v["pick_label"] == "Cheaper"


def twin_pricer(price: float, fee: float):  # noqa: ANN201
    """Both venues at the same price with the same fee per contract: identical in every way."""

    def at(n: int) -> SimpleNamespace:
        def row(venue: str) -> SimpleNamespace:
            cost = round(n * (price + fee), 6)
            return SimpleNamespace(
                venue=venue, market=venue, ok=True, skip=None, side="yes", action="buy", size=n, best_price=price,
                avg_price=price, limit_price=None, fees=round(n * fee, 6), size_at_limit=10_000, cap=None,
                all_in=cost, all_in_per_contract=price + fee, detail=None,
            )

        return SimpleNamespace(venues=[row("kalshi"), row("polymarket_us")])

    return at


def test_identical_on_both_picks_neither() -> None:
    v = spend.spend_view(Match.model_validate(MATCH), "yes", 50, twin_pricer(0.48, 0.02))
    assert v["cheaper"] is None and v["pick_label"] is None
    assert not any(r["cheaper"] for r in v["venues"])
    assert v["headline"]["title"] == "Same on both: your $50 wins $100 either way"
    assert v["headline"]["detail"] == "Kalshi $50.00, Polymarket US $50.00, fees included."


def test_more_payout_gets_the_pays_more_pill() -> None:
    assert view(50, [(0.45, 5000)], [(0.40, 5000)])["pick_label"] == "Pays more"


def test_a_venue_whose_book_runs_out_cant_take_the_amount() -> None:
    # Polymarket US is cheaper but has only 20 for sale near its price: about $8 of the $500. Comparing
    # what $8 wins there with what $500 wins on Kalshi isn't the same bet, so only Kalshi can take $500.
    v = view(500, [(0.45, 5000)], [(0.40, 20)], collar=0.05)
    k, pm = venue(v, "kalshi"), venue(v, "polymarket_us")
    assert pm["depth_limited"] and not pm["ok"] and not pm["cheaper"] and pm["skip"] == "not_enough_size"
    assert pm["skip_line"] == f"Polymarket US can't take $500: it has only {money_label(pm['total_cost'])} for sale near its price."
    assert v["cheaper"] == "kalshi" and k["cheaper"] and v["more"] is None
    assert v["headline"]["title"] == "Buy on Kalshi: the only venue that can take $500 on YES"
    assert v["headline"]["detail"] == (
        f"It wins ${k['contracts']:,} if you're right, fees included. {pm['skip_line']} Spread pays at most 5¢ above a venue's cheapest offer."
    )


def test_the_thin_venue_is_left_out_even_when_it_would_win_more() -> None:
    # Kalshi: $40 of $50 at 10¢ (400 to win). Polymarket US takes all $50 at 40¢. The old answer was
    # "Kalshi pays more" for $40 against $50: now Kalshi can't take $50.
    v = view(50, [(0.10, 400)], [(0.40, 5000)])
    assert v["cheaper"] == "polymarket_us"
    assert venue(v, "kalshi")["skip_line"].startswith("Kalshi can't take $50: it has only $4")


def test_both_books_run_out_is_no_trade() -> None:
    v = view(500, [(0.45, 30)], [(0.40, 20)])
    assert v["cheaper"] is None and not any(r["ok"] for r in v["venues"])
    assert v["headline"]["title"] == "No trade: neither venue can take $500 on YES right now"
    assert "Kalshi can't take $500" in v["headline"]["detail"] and "Polymarket US can't take $500" in v["headline"]["detail"]


def test_a_book_that_runs_out_with_the_money_still_counts() -> None:
    # 111 for sale at 45¢: $50 buys 110 with fees, one more wouldn't fit anyway. The money ran out first.
    v = view(50, [(0.45, 111)], [(0.40, 5000)])
    assert venue(v, "kalshi")["ok"] and v["pick_label"] == "Pays more" and v["more"] > 0


def test_dollar_lines_never_count_contracts() -> None:
    v = view(50, [(0.45, 5000)], [(0.40, 5000)])
    pm = venue(v, "polymarket_us")
    assert pm["cost_line"] == f"{money_label(pm['total_cost'])} at 40¢ avg, {money_label(pm['fees'])} fee included"
    assert "YES at" not in json.dumps(v) and "contract" not in json.dumps(v["headline"])


def test_too_little_for_one_contract_is_one_sentence() -> None:
    v = view(0.3, [(0.45, 5000)], [(0.40, 5000)])
    assert v["cheaper"] is None
    assert v["headline"]["title"] == "No trade: neither venue can take $0.30 on YES right now"
    assert venue(v, "kalshi")["skip_line"].startswith("$0.30 is too little for Kalshi: its smallest bet costs $0.4")


def test_a_venue_that_did_not_answer_leaves_no_answer() -> None:
    m = Match.model_validate(MATCH)
    busy = VenueError("rate_limited", "429", venue="kalshi")
    v = spend.books_view(m, "yes", 50, [book("polymarket_us", PM, [(0.40, 5000)])], failed={"kalshi": busy})
    assert v["cheaper"] is None and v["headline"]["retry"]
    assert v["headline"]["title"] == "Couldn't get Kalshi's price just now, so we can't compare yet."
    assert venue(v, "kalshi")["unavailable"] and venue(v, "polymarket_us")["contracts"] > 0


# --- the endpoint ---------------------------------------------------------------------------------


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path):  # noqa: ANN001, ANN201
    import importlib

    monkeypatch.setenv("LAYER_API_KEY", SECRET)
    monkeypatch.setenv("BOT_STORE_DIR", str(tmp_path))
    for k in ("BOT_MODE", "KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY", "KALSHI_PRIVATE_KEY_PATH", "POLYMARKET_US_KEY_ID", "POLYMARKET_US_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    from spread_engine import app as module

    module = importlib.reload(module)
    monkeypatch.setattr(module.replay, "layer_match", lambda c, t: Match.model_validate(MATCH))
    monkeypatch.setattr(spend, "read_books", lambda c, m: ([book("kalshi", K, [(0.45, 5000)]), book("polymarket_us", PM, [(0.40, 5000)])], {}))
    return module


def test_preview_takes_dollars(engine) -> None:  # noqa: ANN001
    r = local(engine.app).post("/best/preview", json={"match_id": K, "side": "yes", "spend": 50})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["compare"]["spend_label"] == "$50" and body["compare"]["cheaper"] == "polymarket_us"
    assert body["match"]["id"] == K
    assert SECRET not in json.dumps(body)


@pytest.mark.parametrize("extra", [{}, {"size": 10, "spend": 50}])
def test_preview_takes_size_or_spend_not_both(engine, extra) -> None:  # noqa: ANN001
    r = local(engine.app).post("/best/preview", json={"match_id": K, "side": "yes", **extra})
    assert r.status_code == 422


def sdk_spend(amount: float, k_asks: list[tuple[float, float]], pm_asks: list[tuple[float, float]], *, buy: bool):  # noqa: ANN201
    """The SDK's own buy_best(spend=) (or preview_best), in backtest mode on made-up books, and its client."""
    from uselayer import Client

    m = Match.model_validate(MATCH)
    books = [book("kalshi", K, k_asks), book("polymarket_us", PM, pm_asks)]
    out: dict = {}

    def on_book(bc: Client, b: Book) -> None:
        out["seen"] = out.get("seen", 0) + 1
        if out["seen"] == len(books):
            out["r"] = (bc.buy_best if buy else bc.preview_best)(m, "yes", spend=amount)
            out["client"] = bc

    Client(mode="backtest", books=books, store=":memory:", on_alert=lambda e: None).replay(on_book)
    return out["r"], out["client"]


def test_buying_takes_dollars_and_goes_where_they_win_more(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    r, bc = sdk_spend(50, [(0.45, 5000)], [(0.40, 5000)], buy=True)
    asked: dict = {}

    class Sdk:
        rules = bc.rules

        def buy_best(self, *a, **kw):  # noqa: ANN002, ANN003, ANN202
            asked.update(args=a, kw=kw)
            return r

    monkeypatch.setattr(engine, "client", lambda: Sdk())
    res = local(engine.app).post("/best/buy", json={"match_id": K, "side": "yes", "spend": 50})
    assert res.status_code == 200, res.text
    assert asked["args"][1:] == ("yes", None) and asked["kw"] == {"max_price": None, "spend": 50.0}
    body = res.json()
    k, pm = r.why.venues
    assert (body["sent"], body["why"]["spend"], body["why"]["reason_code"]) == (True, 50, "wins_more")
    assert (body["order"]["venue"], body["order"]["size"]) == ("polymarket_us", pm.size) and pm.size > k.size
    assert body["compare"]["verdict"] == (
        f"Polymarket US wins ${pm.size - k.size:,.0f} more if you're right: your $50 buys {pm.size:,g} YES there for "
        f"${pm.all_in:,.2f}, vs {k.size:,g} for ${k.all_in:,.2f} on Kalshi, fees included."
    )
    assert SECRET not in json.dumps(body)


def test_too_little_to_buy_says_so_in_dollars() -> None:
    from spread_engine.views import verdict_line

    r, _ = sdk_spend(0.3, [(0.45, 5000)], [(0.40, 5000)], buy=False)
    assert r.why.size is None and r.order is None
    assert verdict_line(r.why) == "No trade: neither venue can take $0.30 on YES right now."


def test_buying_takes_size_or_spend_not_both(engine) -> None:  # noqa: ANN001
    r = local(engine.app).post("/best/buy", json={"match_id": K, "side": "yes", "size": 10, "spend": 50})
    assert r.status_code == 422


def test_max_price_caps_what_the_amount_buys() -> None:
    # $50: 50 YES at 40¢, then 43¢ (inside the price collar). Uncapped, the money reaches 43¢; capped at 41¢ it can't.
    asks = [(0.40, 50), (0.43, 5000)]
    free = venue(view(50, asks, asks), "kalshi")
    capped = view(50, asks, asks, max_price=0.41)
    assert free["contracts"] > 50
    assert capped["max_price"] == 0.41
    assert all((venue(capped, v)["contracts"] or 0) <= 50 for v in ("kalshi", "polymarket_us"))


def test_preview_in_dollars_keeps_the_max_price(engine) -> None:  # noqa: ANN001
    # Kalshi's YES is 45¢, Polymarket US's 40¢: with a 42¢ cap only Polymarket US can take the $50.
    body = local(engine.app).post("/best/preview", json={"match_id": K, "side": "yes", "spend": 50, "max_price": 0.42}).json()
    c = body["compare"]
    assert c["max_price"] == 0.42 and c["cheaper"] == "polymarket_us"
    assert not venue(c, "kalshi")["contracts"]
