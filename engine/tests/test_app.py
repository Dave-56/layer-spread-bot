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
        "note": "Layer matched these as the same bet (95% confidence).",
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
