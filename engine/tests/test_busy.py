"""Polymarket US says "too many requests": the engine reads fewer books, slower, and stops when told to
(reads.py); a venue that didn't answer is never called "the only venue that can fill"; every skip and
error reads as one plain sentence. All with fakes: no network."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from uselayer import BestOrder, BestVenue, Client, Match, VenueCost, VenueError

from spread_engine import reads, strategies, views
from spread_engine.reads import GatewayReads, cached_books

GW = "https://gateway.polymarket.us"
AT = datetime(2026, 10, 4, tzinfo=UTC)


class Clock:
    """A clock that only moves when something sleeps."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def book_body(price: float = 0.42) -> dict:
    return {
        "marketData": {
            "transactTime": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "bids": [{"px": {"value": str(round(price - 0.02, 2))}, "qty": "500"}],
            "offers": [{"px": {"value": str(price)}, "qty": "500"}],
            "state": "MARKET_STATE_OPEN",
        }
    }


def market_body(slug: str) -> dict:
    return {"markets": [{"slug": slug, "active": True, "closed": False, "status": "MARKET_STATUS_OPEN", "orderPriceMinTickSize": 0.01, "minimumTradeQty": 1}]}


class Venue(httpx.BaseTransport):
    """Polymarket US's gateway, made up: counts every request; ``busy`` answers 429."""

    def __init__(self, busy: int = 0, retry_after: str = "7") -> None:
        self.paths: list[str] = []
        self.busy, self.retry_after = busy, retry_after

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if self.busy:
            self.busy -= 1
            return httpx.Response(429, headers={"retry-after": self.retry_after}, text="<html>rate limited</html>")
        if request.url.path.endswith("/book"):
            return httpx.Response(200, json=book_body(), headers={"date": _http_date(), "cache-control": "public, max-age=30"})
        if request.url.path == "/v1/markets":
            return httpx.Response(200, json=market_body(request.url.params["slug"]))
        return httpx.Response(404, json={"error": "not here"})


def _http_date() -> str:
    from email.utils import format_datetime

    return format_datetime(datetime.now(UTC), usegmt=True)


def get(t: httpx.BaseTransport, path: str) -> httpx.Response:
    with httpx.Client(transport=t) as c:
        return c.get(GW + path)


# ---- reads.py: fewer, slower, and stopping when told to ---------------------------------------------


def test_a_book_is_read_once_inside_cached_books_and_every_time_outside() -> None:
    clock = Clock()
    venue = Venue()
    t = GatewayReads(venue, clock=clock, sleep=clock.sleep, fake_busy=False)
    with cached_books():
        for _ in range(3):
            assert get(t, "/v1/markets/a/book").json()["marketData"]["offers"][0]["px"]["value"] == "0.42"
    assert venue.paths == ["/v1/markets/a/book"] and t.counts["cached"] == 2
    # Outside the block (an order), every read goes to the venue.
    get(t, "/v1/markets/a/book")
    get(t, "/v1/markets/a/book")
    assert len(venue.paths) == 3
    # A cached book is reused for a few seconds only.
    with cached_books():
        clock.t += reads.BOOK_TTL_S + 0.1
        get(t, "/v1/markets/a/book")
    assert len(venue.paths) == 4


def test_a_cached_copy_already_old_at_the_venue_is_not_reused() -> None:
    clock = Clock()

    class Old(Venue):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            self.paths.append(request.url.path)
            return httpx.Response(200, json=book_body(), headers={"age": "12"})

    venue = Old()
    t = GatewayReads(venue, clock=clock, sleep=clock.sleep, fake_busy=False)
    with cached_books():
        get(t, "/v1/markets/a/book")
        get(t, "/v1/markets/a/book")  # the SDK reads again to get a fresh copy: let it
    assert len(venue.paths) == 2


def test_book_reads_are_spaced_to_what_polymarket_us_allows() -> None:
    clock = Clock()
    venue = Venue()
    t = GatewayReads(venue, clock=clock, sleep=clock.sleep, fake_busy=False)
    sent: list[float] = []
    for i in range(10):
        get(t, f"/v1/markets/m{i}/book")
        sent.append(clock.t)
    # Never more than BOOK_READS in any BOOK_WINDOW_S seconds (Polymarket US blocks after ~5 in 10).
    for i, at in enumerate(sent):
        assert sum(1 for x in sent[i:] if x - at < reads.BOOK_WINDOW_S) <= reads.BOOK_READS
    assert sent[: reads.BOOK_READS] == [sent[0]] * reads.BOOK_READS  # a compare's one read never waits
    # Market info and event titles aren't held back by book reads.
    before = clock.t
    get(t, "/v1/markets?slug=x")
    assert clock.t == before


def test_after_a_429_nothing_is_sent_until_retry_after() -> None:
    clock = Clock()
    venue = Venue(busy=1, retry_after="7")
    t = GatewayReads(venue, clock=clock, sleep=clock.sleep, fake_busy=False)
    assert get(t, "/v1/markets/a/book").status_code == 429
    # Held for 7 s: answered here, without a request, so the SDK's retries end quickly.
    held = get(t, "/v1/markets/b/book")
    assert held.status_code == 429 and held.headers["retry-after"] == "0" and len(venue.paths) == 1
    assert get(t, "/v1/markets?slug=b").status_code == 200  # market info isn't blocked with books
    clock.t += 5  # 2 s left: waited out, then sent
    assert get(t, "/v1/markets/b/book").status_code == 200 and venue.paths.count("/v1/markets/b/book") == 1
    assert t.counts["held"] == 1 and t.counts["429"] == 1


def test_a_background_scan_waits_out_a_block() -> None:
    clock = Clock()
    venue = Venue(busy=1, retry_after="7")
    t = GatewayReads(venue, clock=clock, sleep=clock.sleep, fake_busy=False)
    with cached_books(wait_out=15.0):
        r = get(t, "/v1/markets/a/book")
        assert r.status_code == 429 and r.headers["retry-after"] == "7"  # the SDK sleeps it, then retries
        assert get(t, "/v1/markets/b/book").status_code == 200  # waited for the hold, then sent
    assert clock.slept and t.counts["held"] == 0


def test_other_hosts_go_straight_through() -> None:
    clock = Clock()
    venue = Venue(busy=1)
    t = GatewayReads(venue, clock=clock, sleep=clock.sleep, fake_busy=False)
    with httpx.Client(transport=t) as c:
        c.get("https://api.elections.kalshi.com/trade-api/v2/markets/X/orderbook")
        c.get("https://api.elections.kalshi.com/trade-api/v2/markets/X/orderbook")
    assert len(venue.paths) == 2 and t.hold_until == 0 and sum(t.counts.values()) == 0


def test_fake_busy_answers_every_book_with_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPREAD_FAKE_BUSY", "polymarket_us")
    venue = Venue()
    t = GatewayReads(venue)
    assert get(t, "/v1/markets/a/book").status_code == 429 and venue.paths == []
    monkeypatch.delenv("SPREAD_FAKE_BUSY")
    assert GatewayReads(venue).fake_busy is False  # off unless set


# ---- through the SDK: requests for one comparison ---------------------------------------------------

PAIR = Match.model_validate(
    {
        "kalshi": {"market_id": "KXMADEUPGAME-1-A", "group_id": "KXMADEUPGAME-1"},
        "polymarket_us": {"market_id": "madeup-a-b", "group_id": "madeup-a-b"},
    }
)


def sdk(venue: httpx.BaseTransport, monkeypatch: pytest.MonkeyPatch, tmp_path) -> Client:  # noqa: ANN001
    for k in ("KALSHI_KEY_ID", "USELAYER_RECORD", "USELAYER_RECORDED"):
        monkeypatch.delenv(k, raising=False)
    return Client(mode="paper", store=tmp_path / "p.db", on_approval=lambda o, r: False, on_alert=lambda e: None,
                  transport=GatewayReads(venue, fake_busy=False))


def test_one_compare_reads_the_polymarket_us_book_once(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    venue = Venue()
    c = sdk(venue, monkeypatch, tmp_path)
    with cached_books():
        r = c.preview_best(PAIR, "yes", 10)
    assert r.why.venue == "polymarket_us"  # Kalshi has no key here, so it's skipped
    # Before: the comparison read the book, then the preview of the chosen order read it again.
    assert venue.paths == ["/v1/markets", "/v1/markets/madeup-a-b/book"]
    c.close()


def test_a_busy_venue_is_unavailable_not_unable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    venue = Venue()
    c = sdk(venue, monkeypatch, tmp_path)
    c.market("madeup-a-b")  # known already, as after a first look
    venue.busy = 100
    monkeypatch.setattr("uselayer.http.BACKOFF_S", (0, 0, 0))
    t0 = datetime.now(UTC)
    with cached_books():
        r = c.preview_best(PAIR, "yes", 10)
    assert (datetime.now(UTC) - t0).total_seconds() < 6  # the SDK's retries end within seconds
    u = next(v for v in r.why.venues if v.venue == "polymarket_us")
    assert u.skip == "unavailable" and venue.paths.count("/v1/markets/madeup-a-b/book") == 1  # one real 429, then held
    view = views.compare_view(PAIR, r.why)
    assert view["unavailable"] == ["Polymarket US"] and view["cheaper"] is None
    assert view["verdict"] == "Couldn't get Polymarket US's price just now, so we can't compare yet."
    row = next(v for v in view["venues"] if v["venue"] == "polymarket_us")
    assert row["unavailable"] is True and row["skip_reason"] == "Polymarket US is busy right now. Try again in a few seconds."
    c.close()


# ---- the comparison: didn't answer ≠ can't fill ------------------------------------------------------


def cost(venue: str, **kw) -> VenueCost:  # noqa: ANN003
    return VenueCost(venue, "M", "yes", "buy", 100, **kw)


def why(k: VenueCost, u: VenueCost, chosen: VenueCost | None, limit: float | None = None) -> BestVenue:
    code = "only_venue" if chosen else "no_venue"
    return BestVenue("buy", "yes", 100, limit, (k, u), chosen, code, "the SDK's words", None, AT)


OK_K = cost("kalshi", best_price=0.33, limit_price=0.33, avg_price=0.33, cost=33.0, fees=0.53, all_in=33.53, all_in_per_contract=0.3353, size_at_limit=500)


def test_a_venue_that_didnt_answer_leaves_the_comparison_open() -> None:
    busy = cost("polymarket_us", skip="unavailable", detail="polymarket_us said too many requests.")
    v = views.compare_view(PAIR, why(OK_K, busy, OK_K))
    assert v["cheaper"] is None and v["cheaper_name"] is None and v["saving"] is None
    assert v["unavailable"] == ["Polymarket US"]
    assert v["verdict"] == "Couldn't get Polymarket US's price just now, so we can't compare yet."
    assert [r["cheaper"] for r in v["venues"]] == [False, False]
    assert "too many requests" not in json.dumps(v["venues"]) and "polymarket_us said" not in json.dumps(v["venues"])


def test_a_venue_that_answered_and_cant_fill_is_still_the_only_one() -> None:
    closed = cost("polymarket_us", skip="market_closed", detail="madeup isn't open for trading (closed).")
    v = views.compare_view(PAIR, why(OK_K, closed, OK_K))
    assert v["cheaper"] == "kalshi" and v["unavailable"] == []
    assert v["verdict"] == "Only Kalshi can fill 100 contracts: $33.53, fees included."
    assert v["venues"][1]["skip_reason"] == "This market is closed on Polymarket US." and v["venues"][1]["unavailable"] is False


def test_both_didnt_answer() -> None:
    k = cost("kalshi", skip="unavailable", detail="kalshi didn't answer in time.")
    u = cost("polymarket_us", skip="stale_book", detail="The book is 31s old; max_quote_age_s is 10.")
    v = views.compare_view(PAIR, why(k, u, None))
    assert v["verdict"] == "Couldn't get Kalshi's or Polymarket US's prices just now, so we can't compare yet."
    assert v["venues"][0]["skip_reason"] == "Kalshi didn't answer just now. Try again in a few seconds."
    assert v["venues"][1]["skip_reason"] == "Polymarket US's prices are too old to use right now. Try again in a few seconds."


# ---- plain sentences ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "limit", "said"),
    [
        ({"skip": "above_max_price", "best_price": 0.98, "detail": "The best ask is 0.98, above max_price 0.97."}, 0.97, "Polymarket US's cheapest offer is 98¢, above your 97¢ limit."),
        ({"skip": "no_offers", "detail": "Nobody is selling YES on Polymarket US right now."}, None, "Nobody is selling YES on Polymarket US right now."),
        ({"skip": "not_enough_size", "best_price": 0.6, "cap": 0.65, "detail": "Only 40 contracts on Polymarket US at or below 0.65, the limit set by ..."}, None, "Polymarket US doesn't have 100 YES for sale at 65¢ or less."),
        ({"skip": "market_closed", "detail": "x isn't open for trading (closed)."}, None, "This market is closed on Polymarket US."),
        ({"skip": "not_found", "detail": "x"}, None, "Polymarket US doesn't know this market."),
        ({"skip": "unavailable", "detail": "polymarket_us said too many requests."}, None, "Polymarket US is busy right now. Try again in a few seconds."),
        ({"skip": "unavailable", "detail": "Polymarket US is unavailable (503), usually a maintenance window"}, None, "Polymarket US is down for maintenance. Try again later."),
        ({"skip": "unavailable", "detail": "polymarket_us didn't answer in time."}, None, "Polymarket US didn't answer just now. Try again in a few seconds."),
        ({"skip": "stale_book", "detail": "The book is 31s old; max_quote_age_s is 10."}, None, "Polymarket US's prices are too old to use right now. Try again in a few seconds."),
        ({"skip": "no_key", "detail": "x"}, None, "Add your Polymarket US key to .env to price it here."),
        ({"skip": "switched_off", "detail": "x"}, None, "This release doesn't trade on Polymarket US."),
        ({"skip": "not_allowed", "detail": "x"}, None, "Your rules don't allow this order on Polymarket US."),
        ({"skip": "invalid_order", "detail": "x"}, None, "This order breaks Polymarket US's price step or minimum size."),
        ({"skip": "no_book", "detail": "x"}, None, "There's no book for this market on Polymarket US."),
    ],
)
def test_every_skip_is_one_plain_sentence(kw: dict, limit: float | None, said: str) -> None:
    assert views.skip_sentence(cost("polymarket_us", **kw), limit) == said


def test_every_skip_code_has_a_sentence() -> None:
    from uselayer import best

    codes = {"switched_off", "no_key", "not_allowed", "not_found", "market_closed", "no_book", "stale_book", "no_offers",
             "above_max_price", "below_min_price", "not_enough_size", "invalid_order", "not_held", "unavailable"}
    for code in codes:
        assert f"({code})" in best.__doc__ or f"``{code}``" in best.__doc__  # the SDK's own list
        s = views.skip_sentence(cost("kalshi", skip=code, detail="raw SDK words"))
        assert s and s.endswith(".") and "raw SDK words" not in s and "kalshi" not in s


@pytest.mark.parametrize(
    ("err", "said"),
    [
        (VenueError("rate_limited", "polymarket_us said too many requests.", venue="polymarket_us", status=429, hint="The SDK already paces..."), "Polymarket US is busy right now. Try again in a few seconds."),
        (VenueError("venue_unavailable", "kalshi didn't answer in time.", venue="kalshi"), "Kalshi didn't answer just now. Try again in a few seconds."),
        (VenueError("venue_maintenance", "Polymarket US is unavailable (503)...", venue="polymarket_us", status=503), "Polymarket US is down for maintenance. Try again later."),
        (VenueError("auth_failed", "Kalshi books are read with your own API key for it.", venue="kalshi"), "Add your Kalshi key to .env, then restart."),
        (VenueError("auth_failed", "kalshi refused the credentials: bad sig", venue="kalshi", status=401), "Kalshi didn't accept your key. Check it in .env, then restart."),
        (VenueError("not_available", "No venue can take this order. Kalshi: ...", raw={"venues": []}), "Neither venue can take this order right now."),
    ],
)
def test_errors_are_one_plain_sentence(err: VenueError, said: str) -> None:
    v = views.error_view(err)
    assert v["message"] == said and v["hint"] is None and v["detail"] == err.message


def test_an_unmapped_error_keeps_the_sdks_sentence_and_hint() -> None:
    e = VenueError("blocked_by_rule", "Blocked by budget: this order would put $120 at risk.", hint="Raise the budget.")
    assert views.error_view(e)["message"] == e.message and views.error_view(e)["hint"] == "Raise the budget."


# ---- strategies: read fewer, and a busy venue isn't "no trade" ------------------------------------


def _m(mid: str) -> Match:
    from datetime import timedelta

    later = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
    return Match.model_validate(
        {"kalshi": {"market_id": mid, "series": "KXMADEUPGAME", "event_time": later}, "polymarket_us": {"market_id": f"pm-{mid}"}}
    )


class _Leg:
    def __init__(self, ask: float) -> None:
        self.yes_ask = ask


class _Prices:
    def __init__(self, ask: float) -> None:
        self.a, self.b = _Leg(ask), _Leg(ask)


class _Open:
    open = True


class _Client:
    def __init__(self, busy: bool = False) -> None:
        self.read: list[str] = []
        self.busy = busy

    def market(self, market_id: str, *, venue: str) -> _Open:
        return _Open()

    def prices(self, m: Match) -> _Prices:
        self.read.append(m.kalshi.market_id)
        if self.busy:
            raise VenueError("rate_limited", "polymarket_us said too many requests.", venue="polymarket_us")
        return _Prices(0.6)


def test_priced_reads_only_a_little_ahead_of_what_the_strategy_uses() -> None:
    c = _Client()
    ms = [_m(f"M{i}") for i in range(10)]
    gen = strategies.priced(ms, c)  # type: ignore[arg-type]
    first = next(gen)
    gen.close()
    assert first[0].kalshi.market_id == "M0"
    # Before: all 10 were queued at once, 4 reading at a time. Now only the one the strategy used.
    assert c.read == ["M0"]


def test_a_busy_venue_is_noted_not_skipped_silently() -> None:
    c = _Client(busy=True)
    with strategies.read_failures() as failed:
        assert list(strategies.priced([_m("A"), _m("B")], c)) == []  # type: ignore[arg-type]
    assert failed == {"polymarket_us"}


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path):  # noqa: ANN001, ANN201
    monkeypatch.setenv("LAYER_API_KEY", "lyr_test")
    monkeypatch.setenv("BOT_STORE_DIR", str(tmp_path))
    monkeypatch.delenv("BOT_MODE", raising=False)
    from spread_engine import app as module

    return importlib.reload(module)


def test_a_strategy_that_couldnt_read_says_so_not_no_trade(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(engine, "_list_in", lambda q, cats, limit, upcoming_only=False: ([_m("A"), _m("B")], 0))
    monkeypatch.setattr(engine, "client", lambda: _Client(busy=True))
    c = TestClient(engine.app, base_url="http://127.0.0.1:8765", headers={"x-spread-proxy": "1"})
    body = c.get("/best/signal", params={"strategy": "sports_favorite"}).json()
    assert body["signal"] is None and body["unavailable"] is True
    assert body["no_trade"] == "Couldn't get Polymarket US's prices just now, so there's no answer yet."


def test_layer_is_asked_for_small_pages() -> None:
    from spread_engine.app import page_size

    assert (page_size(30), page_size(50), page_size(10), page_size(100), page_size(500)) == (60, 100, 40, 200, 200)


def test_every_market_counts_a_venue_that_didnt_answer_as_couldnt_check() -> None:
    from spread_engine import every_market

    best = {"ok": True, "why": {"reason_code": "only_venue", "venue": "kalshi"}, "compare": {"unavailable": ["Polymarket US"]}}
    assert every_market.outcome(best) == "error"
    best["compare"]["unavailable"] = []
    assert every_market.outcome(best) == "one_venue"


def test_the_arbitrage_scan_is_paced_with_the_engine(engine) -> None:  # noqa: ANN001
    # One transport (one window) for the engine's client and the scan's, so their reads add up.
    assert engine.gateway() is engine.gateway() and engine.gateway().keep_open
    assert engine.scan_client()._http._client._transport is engine.gateway()
