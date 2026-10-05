from __future__ import annotations

from uselayer import Match

from spread_engine.strategy import decide


def m(mid: str, when: str | None, caveats: list[str] | None = None) -> Match:
    return Match.model_validate(
        {
            "caveats": caveats or [],
            "kalshi": {"market_id": mid, "event_time": when},
            "polymarket_us": {"market_id": f"pm-{mid}"},
        }
    )


def test_example_skips_started_and_rule_differences() -> None:
    sig = decide([m("PAST", "2020-01-01T00:00:00Z"), m("RULES", "2099-01-01T00:00:00Z", ["timing_differs"]), m("OK", "2099-01-01T00:00:00Z")])
    assert sig is not None and sig.match.kalshi.market_id == "OK"
    assert (sig.side, sig.size) == ("yes", 100)


class _Leg:
    def __init__(self, yes_ask: float | None) -> None:
        self.yes_ask = yes_ask


class _Prices:
    def __init__(self, a: float | None, b: float | None) -> None:
        self.a, self.b = _Leg(a), _Leg(b)


class _Client:
    def __init__(self, asks: dict[str, tuple[float | None, float | None]]) -> None:
        self.asks = asks

    def prices(self, match: Match) -> _Prices:
        return _Prices(*self.asks[match.kalshi.market_id])


def test_example_needs_yes_on_offer_on_both_venues() -> None:
    later = "2099-01-01T00:00:00Z"
    client = _Client({"EMPTY": (None, 0.4), "OK": (0.41, 0.42)})
    sig = decide([m("EMPTY", later), m("OK", later)], client)  # type: ignore[arg-type]
    assert sig is not None and sig.match.kalshi.market_id == "OK"


def test_no_trade_when_nothing_fits() -> None:
    assert decide([]) is None
    assert decide([m("PAST", "2020-01-01T00:00:00Z")]) is None
