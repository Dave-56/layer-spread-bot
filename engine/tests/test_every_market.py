"""Best venue for every market (POST /best/scan): the next markets in a category, each compared, streamed."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_app import MADE_UP, _best, local
from uselayer import Match, VenueCost, VenueError


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path):  # noqa: ANN001, ANN201
    monkeypatch.setenv("LAYER_API_KEY", "lyr_test")
    monkeypatch.setenv("BOT_STORE_DIR", str(tmp_path))
    monkeypatch.delenv("BOT_MODE", raising=False)
    from spread_engine import app as module

    return importlib.reload(module)


def made_up(n: int, *, hours: int, caveats: list[str] | None = None) -> Match:
    """A made-up match ``n`` whose game starts in ``hours`` hours."""
    t = (datetime.now(UTC) + timedelta(hours=hours)).isoformat()
    d = json.loads(json.dumps(MADE_UP))
    d["caveats"] = caveats or []
    d["kalshi"].update(market_id=f"KXMADEUPGAME-{n}-A", event_time=t)
    d["polymarket_us"].update(market_id=f"madeup-{n}:long", event_time=t)
    return Match.model_validate(d)


FAILS = "KXMADEUPGAME-3-A"  # this one's comparison fails: Polymarket US says too many requests


def scan(engine, monkeypatch, listed, *, started=0, body=None):  # noqa: ANN001, ANN202
    """POST /best/scan against a made-up listing and SDK client: (what was asked of Layer, the events)."""
    asked: list = []

    def listing(q, cats, limit, upcoming_only=False):  # noqa: ANN001, ANN202
        asked.append((cats, upcoming_only))
        return listed, started

    class _C:
        def preview_best(self, m, side, size, max_price=None):  # noqa: ANN001, ANN202
            if m.kalshi.market_id == FAILS:
                raise VenueError("rate_limited", "polymarket_us said too many requests.", venue="polymarket_us")
            return _best(m)

    monkeypatch.setattr(engine, "_list_in", listing)
    monkeypatch.setattr(engine, "client", lambda: _C())
    r = local(engine.app).post("/best/scan", json=body or {})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    return asked, [json.loads(line) for line in r.text.splitlines() if line]


def test_the_next_markets_compared_and_streamed(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    later = made_up(1, hours=9)
    worded = made_up(2, hours=2, caveats=["source_differs"])
    failed = made_up(3, hours=3)
    soon = made_up(4, hours=1)
    asked, events = scan(engine, monkeypatch, [later, worded, failed, soon], body={"category": "sports", "limit": 3})
    assert asked == [(("sports",), True)]  # Layer's sports category, games that haven't started
    start, *rows, done = events
    assert start == {"type": "start", "total": 3, "category": "Sports", "size": 100, "side": "yes", "empty": None}
    # The next 3 games; the one 9 hours out is left out.
    by = {r["match"]["id"]: r for r in rows}
    assert set(by) == {"KXMADEUPGAME-4-A", "KXMADEUPGAME-2-A", FAILS}

    ok = by["KXMADEUPGAME-4-A"]
    assert ok["outcome"] == "kalshi"
    assert ok["order"] == {"match_id": "KXMADEUPGAME-4-A", "side": "yes", "size": 100, "max_price": None}
    # The same compare view as the strategy path, from the SDK's own result.
    assert ok["best"]["ok"] is True and ok["best"]["why"]["reason_code"] == "cheaper"
    assert ok["best"]["compare"]["verdict"] == "Kalshi is $0.97 cheaper for 100 contracts, fees included: $59.71 vs $60.68."

    # Rules differ slightly: priced and kept, with Layer's warning.
    w = by["KXMADEUPGAME-2-A"]
    assert w["outcome"] == "kalshi"
    assert w["match"]["rule_warning"] == "Rules differ slightly on where the result comes from. Both pay the same in normal cases, but in a rare case one could pay and the other not."

    # A comparison that failed is a row with one plain sentence; the scan goes on.
    f = by[FAILS]
    assert f["outcome"] == "error" and f["best"]["ok"] is False
    assert f["best"]["error_line"] == "Polymarket US is busy right now. Try again in a few seconds."

    assert done == {"type": "done", "total": 3, "counts": {"kalshi": 2, "polymarket_us": 0, "same": 0, "one_venue": 0, "neither": 0, "error": 1}}


def test_every_empty_result_says_why(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    asked, events = scan(engine, monkeypatch, [], body={"category": "crypto"})
    assert asked == [(("crypto",), True)]
    assert events[0]["empty"] == "Layer has no crypto markets matched on both Kalshi and Polymarket US right now."
    assert events[-1] == {"type": "done", "total": 0, "counts": dict.fromkeys(("kalshi", "polymarket_us", "same", "one_venue", "neither", "error"), 0)}

    asked, events = scan(engine, monkeypatch, [], started=41, body={"category": "news"})
    assert asked == [(("politics", "economics", "culture"), True)]
    assert events[0]["empty"] == "All 41 news, politics, economics or culture markets matched on both venues have already started or finished."


def test_bounded_and_guarded(engine) -> None:  # noqa: ANN001
    c = local(engine.app)
    assert c.post("/best/scan", json={"category": "everything"}).status_code == 422
    assert c.post("/best/scan", json={"limit": 51}).status_code == 422
    bare = TestClient(engine.app, base_url="http://127.0.0.1:8765")
    assert bare.post("/best/scan", content="{}").status_code == 415  # not JSON
    assert bare.post("/best/scan", content="{}", headers={"content-type": "text/plain"}).status_code == 415
    assert bare.post("/best/scan", json={}).status_code == 403  # no proxy header
    rebound = TestClient(engine.app, base_url="http://evil.example:8765", headers={"x-spread-proxy": "1"})
    assert rebound.post("/best/scan", json={}).status_code == 403  # a site pointed at 127.0.0.1
    remote = TestClient(engine.app, client=("203.0.113.9", 5000), headers={"x-spread-proxy": "1"})
    assert remote.post("/best/scan", json={}).status_code == 403


def test_skip_reasons_are_plain_sentences() -> None:
    from spread_engine.views import SKIP, skip_line

    def v(skip: str, venue: str = "polymarket_us") -> VenueCost:
        return VenueCost(venue, "m", "yes", "buy", 100, skip=skip, detail="The best ask is 0.98, above max_price 0.97.")

    assert skip_line(v("not_enough_size")) == "Polymarket US doesn't have 100 YES for sale near its best price."
    assert skip_line(v("stale_book")) == "Polymarket US's prices are too old to use right now. Try again in a few seconds."
    assert skip_line(v("no_offers", "kalshi")) == "Nobody is selling YES on Kalshi right now."
    assert skip_line(v("above_max_price")) == "Polymarket US's cheapest YES costs more than your max price."
    for code in SKIP:  # every code: one sentence, none of the SDK's setting names
        line = skip_line(v(code))
        assert line and line.endswith(".") and "_" not in line and "0.9" not in line
    assert skip_line(VenueCost("kalshi", "m", "yes", "buy", 100)) is None
