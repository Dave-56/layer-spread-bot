"""The engine's safety rules: paper by default, keys never echoed, local requests only."""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

SECRET = "lyr_do_not_echo_0123456789"


def local(app):  # noqa: ANN001, ANN201
    """The engine as the app's proxy calls it: this machine's address, with the proxy header."""
    return TestClient(app, base_url="http://127.0.0.1:8765", headers={"x-spread-proxy": "1"})


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path):  # noqa: ANN001, ANN201
    monkeypatch.setenv("LAYER_API_KEY", SECRET)
    monkeypatch.setenv("BOT_STORE_DIR", str(tmp_path))
    for k in ("BOT_MODE", "KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY", "KALSHI_PRIVATE_KEY_PATH", "POLYMARKET_US_KEY_ID", "POLYMARKET_US_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    from spread_engine import app as module

    return importlib.reload(module)


def test_paper_by_default_and_keys_are_yes_no_only(engine) -> None:  # noqa: ANN001
    body = local(engine.app).get("/status").json()
    assert body["mode"] == "paper"
    assert body["keys"] == {"layer": True, "kalshi": False, "polymarket_us": False}
    assert SECRET not in json.dumps(body)


def test_live_needs_the_exact_word(monkeypatch: pytest.MonkeyPatch) -> None:
    from spread_engine import config

    for value, mode in (("paper", "paper"), ("LIVE", "live"), ("yes", "paper"), ("", "paper")):
        monkeypatch.setenv("BOT_MODE", value)
        assert config.load().mode == mode


def test_answers_only_this_machine(engine) -> None:  # noqa: ANN001
    remote = TestClient(engine.app, client=("203.0.113.9", 5000))
    assert remote.get("/status").status_code == 403


def test_paper_account_starts_empty_and_resets(engine, tmp_path) -> None:  # noqa: ANN001
    c = local(engine.app)
    acct = c.get("/paper/account").json()
    assert acct == {**acct, "at_risk": 0, "positions": [], "budget": 100.0}
    assert acct["store"].startswith(str(tmp_path))  # the test's own store, never the user's
    assert c.post("/paper/reset", json={}).json()["at_risk"] == 0


def test_reset_is_paper_only(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    from spread_engine import config

    monkeypatch.setenv("BOT_MODE", "live")
    monkeypatch.setenv("BOT_STORE_DIR", str(tmp_path))
    from spread_engine import app as module

    module.settings = config.load()
    try:
        assert local(module.app).post("/paper/reset", json={}).status_code == 403
    finally:
        monkeypatch.setenv("BOT_MODE", "paper")
        module.settings = config.load()


def test_unknown_match_is_a_clear_404(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from uselayer import VenueError

    def none(client, ticker):  # noqa: ANN001, ANN202
        raise VenueError("not_found", "no match")

    monkeypatch.setattr(engine.replay, "layer_match", none)
    r = local(engine.app).post("/best/preview", json={"match_id": "KXNOPE", "side": "yes", "size": 10})
    assert r.status_code == 404 and r.json()["detail"] == "Layer has no Polymarket US match for KXNOPE. Search for the market first."


MADE_UP = {
    "confidence": 0.95,
    "caveats": [],
    "kalshi": {"market_id": "KXMADEUPGAME-1-A", "group_id": "KXMADEUPGAME-1", "event": "A vs B", "outcome": "A", "url": "https://kalshi.example/a"},
    "polymarket_us": {"market_id": "madeup-a-b:long", "group_id": "madeup-a-b", "event": "A vs. B", "outcome": "A", "url": "https://polymarket.example/a-b"},
}


def _best(match):  # noqa: ANN001, ANN202
    """A made-up comparison, built from the SDK's own result types: Kalshi $0.97 cheaper for 100 YES."""
    from datetime import UTC, datetime

    from uselayer import BestOrder, BestVenue, VenueCost

    at = datetime(2026, 10, 4, tzinfo=UTC)
    k = VenueCost("kalshi", match.kalshi.market_id, "yes", "buy", 100, best_price=0.58, limit_price=0.58, avg_price=0.58, cost=58.0, fees=1.71, all_in=59.71, all_in_per_contract=0.5971, size_at_limit=954.5)
    u = VenueCost("polymarket_us", match.polymarket_us.market_id, "yes", "buy", 100, best_price=0.585, limit_price=0.59, avg_price=0.59, cost=59.0, fees=1.68, all_in=60.68, all_in_per_contract=0.6068, size_at_limit=10675)
    why = BestVenue("buy", "yes", 100, None, (k, u), k, "cheaper", "Kalshi is cheaper.", 0.97, at)
    return BestOrder(None, why, False)


def test_preview_found_by_ticker_alone_and_labelled(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from uselayer import Match

    looked: list[str] = []

    def lookup(client, ticker):  # noqa: ANN001, ANN202
        looked.append(ticker)
        return Match.model_validate(MADE_UP)

    class _C:
        def preview_best(self, m, side, size, max_price=None):  # noqa: ANN001, ANN202
            return _best(m)

    monkeypatch.setattr(engine.replay, "layer_match", lookup)
    monkeypatch.setattr(engine, "client", lambda: _C())
    body = local(engine.app).post("/best/preview", json={"match_id": "KXMADEUPGAME-1-A", "side": "yes", "size": 100}).json()
    assert looked == ["KXMADEUPGAME-1-A"] and body["ok"] is True
    assert body["match"]["event_key"] == "KXMADEUPGAME-1"
    cmp = body["compare"]
    assert cmp["pair"] == {
        "kalshi": {"title": "A vs B", "outcome": "A", "question": None, "ticker": "KXMADEUPGAME-1-A", "url": "https://kalshi.example/a"},
        "polymarket_us": {"title": "A vs. B", "outcome": "A", "question": None, "slug": "madeup-a-b:long", "url": "https://polymarket.example/a-b"},
        "note": "Layer is 95% sure these are the same bet.",
        "confidence": 0.95,
        "rule_warning": None,
    }
    k, u = cmp["venues"]
    assert (k["price_label"], k["chance_label"], k["fillable"], k["total_cost"], k["cheaper"]) == ("58¢", "58%", 954, 59.71, True)
    assert (u["price_label"], u["chance_label"], u["cheaper"]) == ("58.5¢", "58.5%", False)
    assert (cmp["cheaper"], cmp["cheaper_name"], cmp["saving"], cmp["saving_label"]) == ("kalshi", "Kalshi", 0.97, "$0.97")
    assert cmp["verdict"] == "Kalshi is $0.97 cheaper for 100 contracts, fees included: $59.71 vs $60.68."
    assert body["why"]["venue"] == "kalshi"  # the SDK's own result is still there, unchanged


def test_strategies_are_listed_by_category(engine) -> None:  # noqa: ANN001
    body = local(engine.app).get("/strategies").json()
    assert body["categories"] == ["Sports", "Crypto", "News, politics & economics", "Your own"]
    assert {s["category"] for s in body["strategies"]} <= set(body["categories"])


def test_add_a_strategy_from_the_app(engine, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    import sys

    monkeypatch.setattr(engine.strategies, "FOLDER", tmp_path)
    monkeypatch.setattr(engine.strategies, "__path__", [str(tmp_path), *engine.strategies.__path__])
    c = local(engine.app)
    try:
        bad = c.post("/strategies", json={"filename": "mine_app.py", "code": "def decide(:\n"})
        assert bad.status_code == 422 and bad.json()["detail"].startswith("mine_app.py didn't load. Line 1:")
        ok = c.post("/strategies", json={"filename": "mine_app.py", "code": "NAME = 'Mine'\ndef decide(m, c):\n    return None\n"}).json()
        assert ok["added"]["id"] == "mine_app" and ok["added"]["category"] == "Your own"
        assert [s["id"] for s in ok["strategies"]] == ["mine_app"]
    finally:
        sys.modules.pop("spread_engine.strategies.mine_app", None)


def test_the_starter_file_is_a_download_not_a_choice(engine) -> None:  # noqa: ANN001
    c = local(engine.app)
    body = c.get("/strategies/starter").json()
    assert body["filename"] == "my_strategy.py" and "def decide(" in body["code"]
    assert "my_strategy" not in [s["id"] for s in c.get("/strategies").json()["strategies"]]


def test_no_trade_says_the_strategy_sentence(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    asked: list = []

    def listing(q, cats, limit, upcoming_only=False):  # noqa: ANN001, ANN202
        asked.append(cats)
        return [], 0

    monkeypatch.setattr(engine, "_list_in", listing)
    monkeypatch.setattr(engine, "client", lambda: None)
    body = local(engine.app).get("/best/signal", params={"strategy": "crypto_near_certain"}).json()
    assert asked == [("crypto",)]  # the template's own Layer category
    assert body["signal"] is None and body["best"] is None
    assert body["no_trade"] == "No trade: Layer has no crypto markets matched on both Kalshi and Polymarket US right now."


def test_a_post_must_be_json_from_the_app(engine) -> None:  # noqa: ANN001
    body = {"filename": "mine_x.py", "code": "def decide(m, c):\n    return None\n"}
    bare = TestClient(engine.app, base_url="http://127.0.0.1:8765")
    # A cross-site page can send a POST with no content-type, or as text/plain, and no custom header.
    assert bare.post("/strategies", content=json.dumps(body)).status_code == 415
    assert bare.post("/strategies", content=json.dumps(body), headers={"content-type": "text/plain"}).status_code == 415
    no_header = bare.post("/strategies", json=body)
    assert no_header.status_code == 403 and "x-spread-proxy" in no_header.json()["error"]
    assert bare.post("/paper/reset", json={}).status_code == 403
    assert bare.get("/status").status_code == 200  # reads need neither


def test_a_site_pointed_at_127_0_0_1_is_refused(engine) -> None:  # noqa: ANN001
    rebound = TestClient(engine.app, base_url="http://evil.example:8765", headers={"x-spread-proxy": "1"})
    assert rebound.get("/status").status_code == 403
    assert rebound.post("/paper/reset", json={}).status_code == 403
    for host in ("localhost:8765", "[::1]:8765", "127.0.0.1"):
        assert TestClient(engine.app, base_url=f"http://{host}").get("/status").status_code == 200


def _caveat_match():  # noqa: ANN202
    from uselayer import Match

    return Match.model_validate(
        {
            "caveats": ["timing_differs"],
            "kalshi": {"market_id": "KXMADEUP-1", "outcome": "A", "event_time": "2099-01-01T00:00:00Z"},
            "polymarket_us": {"market_id": "madeup-a"},
        }
    )


def test_a_strategy_that_picks_a_match_worded_differently_shows_the_warning(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    from spread_engine.strategies import Signal

    mt = _caveat_match()
    monkeypatch.setattr(engine, "_list_in", lambda *a, **k: ([mt], 0))
    monkeypatch.setattr(engine, "client", lambda: None)
    pick = SimpleNamespace(decide=lambda ms, c: Signal(ms[0], "yes", 10, why="made up"))
    monkeypatch.setattr(engine.strategies, "module", lambda sid: pick)
    monkeypatch.setattr(engine, "_preview", lambda b: {"ok": True})
    sig = local(engine.app).get("/best/signal", params={"strategy": "any"}).json()["signal"]
    assert sig["match"]["rule_warning"].startswith("Rules differ slightly on when the result is checked")


def test_paper_trade_result_carries_the_warning(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from datetime import UTC, datetime

    from uselayer import Quote

    now = datetime(2026, 10, 4, tzinfo=UTC)
    q = Quote(a=None, b=None, contracts=0, min_edge=0.01, edge_at_best=None, net_profit=0.0, net_profit_per_contract=0.0, fees=0.0, cost=0.0, return_pct=0.0, limited_by="no_asks", as_of=now)

    class _Trade:
        quote = q

        def to_dict(self) -> dict:
            return {"status": "missed", "hedged": 0, "locked_in": 0, "unwind_loss": 0, "notes": []}

    class _C:
        def trade(self, *a, **k):  # noqa: ANN002, ANN003, ANN202
            return _Trade()

    mt = _caveat_match()
    engine._matches[mt.kalshi.market_id] = mt
    monkeypatch.setattr(engine, "client", lambda: _C())
    body = local(engine.app).post("/arb/trade", json={"match_id": "KXMADEUP-1", "size": 5}).json()
    assert body["mode"] == "paper" and body["rule_warning"].endswith("in a rare case one could pay and the other not.")


def test_replay_before_the_fee_schedule_is_one_plain_sentence(engine, tmp_path) -> None:  # noqa: ANN001
    lines = [
        {"kind": "book", "venue": v, "market": mk, "bids": [{"price": 0.4, "size": 1}], "asks": [{"price": 0.42, "size": 1}], "as_of": f"2025-10-20T12:00:0{i}Z"}
        for i, (v, mk) in enumerate([("kalshi", "KXMADEUP-1"), ("polymarket_us", "madeup-a"), ("kalshi", "KXMADEUP-1")])
    ]
    f = tmp_path / "early.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    f.with_suffix(".match.json").write_text(_caveat_match().model_dump_json())
    r = local(engine.app).post("/replay/run", json={"path": str(f)})
    assert r.status_code == 422
    assert r.json()["detail"].startswith("Can't replay this file: it's from before Nov 3, 2025")


class _Stale:
    """A client whose trade() finds a book over 10 s old ``stale`` times, then trades."""

    def __init__(self, stale: int, error: Exception | None = None) -> None:
        self.calls, self.stale, self.error = 0, stale, error

    def trade(self, *a, **k):  # noqa: ANN002, ANN003, ANN202
        from uselayer import VenueError

        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.calls <= self.stale:
            raise VenueError("stale_quote", "The polymarket_us book for madeup-a is older than max_quote_age_s.", venue="polymarket_us")
        return _made_up_trade()


def _made_up_trade():  # noqa: ANN202
    from datetime import UTC, datetime

    from uselayer import Quote

    q = Quote(a=None, b=None, contracts=0, min_edge=0.01, edge_at_best=None, net_profit=0.0, net_profit_per_contract=0.0, fees=0.0, cost=0.0, return_pct=0.0, limited_by="no_asks", as_of=datetime(2026, 10, 4, tzinfo=UTC))

    class _Trade:
        quote = q

        def to_dict(self) -> dict:
            return {"status": "missed", "hedged": 0, "locked_in": 0, "unwind_loss": 0, "notes": []}

    return _Trade()


def test_paper_trade_reads_a_stale_book_once_more(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    mt = _caveat_match()
    engine._matches[mt.kalshi.market_id] = mt
    once = _Stale(stale=1)
    monkeypatch.setattr(engine, "client", lambda: once)
    assert local(engine.app).post("/arb/trade", json={"match_id": "KXMADEUP-1", "size": 5}).status_code == 200
    assert once.calls == 2

    twice = _Stale(stale=2)
    monkeypatch.setattr(engine, "client", lambda: twice)
    r = local(engine.app).post("/arb/trade", json={"match_id": "KXMADEUP-1", "size": 5})
    assert r.status_code == 409 and twice.calls == 2
    assert r.json()["detail"] == "Polymarket US's prices were more than 10 seconds old, so nothing was bought. Try again."


def test_a_blocked_trade_is_one_plain_sentence(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from uselayer import VenueError

    mt = _caveat_match()
    engine._matches[mt.kalshi.market_id] = mt
    blocked = VenueError("blocked_by_rule", "$140.00 would be at risk in total; the budget is $100.", rule="budget")
    monkeypatch.setattr(engine, "client", lambda: _Stale(0, blocked))
    r = local(engine.app).post("/arb/trade", json={"match_id": "KXMADEUP-1", "size": 5})
    assert r.status_code == 409 and r.json()["detail"].startswith("This trade would take your account over its limit, so nothing was bought.")


def test_preview_reads_again_once_when_a_book_was_too_old(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from dataclasses import replace

    from uselayer import BestOrder, Match

    fresh = _best(Match.model_validate(MADE_UP))
    k, u = fresh.why.venues
    stale = BestOrder(None, replace(fresh.why, venues=(k, replace(u, skip="stale_book", detail="The book is 12s old; max_quote_age_s is 10."))), False)
    answers = [stale, fresh]

    class _C:
        def preview_best(self, m, side, size, max_price=None):  # noqa: ANN001, ANN202
            return answers.pop(0)

    monkeypatch.setattr(engine.replay, "layer_match", lambda c, t: Match.model_validate(MADE_UP))
    monkeypatch.setattr(engine, "client", lambda: _C())
    body = local(engine.app).post("/best/preview", json={"match_id": "KXMADEUPGAME-1-A", "side": "yes", "size": 100}).json()
    assert answers == [] and [v["skip"] for v in body["compare"]["venues"]] == [None, None]
