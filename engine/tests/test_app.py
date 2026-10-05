"""The engine's safety rules: paper by default, keys never echoed, local requests only."""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

SECRET = "lyr_do_not_echo_0123456789"


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path):  # noqa: ANN001, ANN201
    monkeypatch.setenv("LAYER_API_KEY", SECRET)
    monkeypatch.setenv("BOT_STORE_DIR", str(tmp_path))
    for k in ("BOT_MODE", "KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY", "KALSHI_PRIVATE_KEY_PATH", "POLYMARKET_US_KEY_ID", "POLYMARKET_US_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    from spread_engine import app as module

    return importlib.reload(module)


def test_paper_by_default_and_keys_are_yes_no_only(engine) -> None:  # noqa: ANN001
    body = TestClient(engine.app).get("/status").json()
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
    c = TestClient(engine.app)
    acct = c.get("/paper/account").json()
    assert acct == {**acct, "at_risk": 0, "positions": [], "budget": 100.0}
    assert acct["store"].startswith(str(tmp_path))  # the test's own store, never the user's
    assert c.post("/paper/reset").json()["at_risk"] == 0


def test_reset_is_paper_only(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    from spread_engine import config

    monkeypatch.setenv("BOT_MODE", "live")
    monkeypatch.setenv("BOT_STORE_DIR", str(tmp_path))
    from spread_engine import app as module

    module.settings = config.load()
    try:
        assert TestClient(module.app).post("/paper/reset").status_code == 403
    finally:
        monkeypatch.setenv("BOT_MODE", "paper")
        module.settings = config.load()


def test_unknown_match_is_a_clear_404(engine) -> None:  # noqa: ANN001
    r = TestClient(engine.app).post("/best/preview", json={"match_id": "KXNOPE", "side": "yes", "size": 10})
    assert r.status_code == 404 and "Load matches first" in r.json()["detail"]


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
    from spread_engine.strategies import Signal

    mt = _caveat_match()
    monkeypatch.setattr(engine, "_list", lambda *a, **k: ([mt], 0))
    monkeypatch.setattr(engine, "client", lambda: None)
    monkeypatch.setattr(engine.strategies, "get", lambda sid: lambda ms, c: Signal(ms[0], "yes", 10, why="made up"))
    monkeypatch.setattr(engine, "_preview", lambda b: {"ok": True})
    sig = TestClient(engine.app).get("/best/signal", params={"strategy": "any"}).json()["signal"]
    assert sig["match"]["rule_warning"].startswith("Worded differently: different deadline")


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
    body = TestClient(engine.app).post("/arb/trade", json={"match_id": "KXMADEUP-1", "size": 5}).json()
    assert body["mode"] == "paper" and body["rule_warning"].endswith("The two could settle differently.")


def test_replay_before_the_fee_schedule_is_one_plain_sentence(engine, tmp_path) -> None:  # noqa: ANN001
    lines = [
        {"kind": "book", "venue": v, "market": mk, "bids": [{"price": 0.4, "size": 1}], "asks": [{"price": 0.42, "size": 1}], "as_of": f"2026-09-20T12:00:0{i}Z"}
        for i, (v, mk) in enumerate([("kalshi", "KXMADEUP-1"), ("polymarket_us", "madeup-a"), ("kalshi", "KXMADEUP-1")])
    ]
    f = tmp_path / "early.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    f.with_suffix(".match.json").write_text(_caveat_match().model_dump_json())
    r = TestClient(engine.app).post("/replay/run", json={"path": str(f)})
    assert r.status_code == 422
    assert r.json()["detail"].startswith("Can't replay this file: it's from before Sep 25, 2026")
