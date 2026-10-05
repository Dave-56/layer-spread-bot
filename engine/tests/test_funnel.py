"""The funnel's gates, with a fake quoter (no network). Quotes are built the way the SDK returns them."""

from __future__ import annotations

from datetime import UTC, datetime

from uselayer import Match, Quote, QuoteLeg, VenueError

from spread_engine.funnel import ScanSettings, judge, scan

NOW = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)


def match(mid: str = "KXTEST-1", caveats: list[str] | None = None) -> Match:
    return Match.model_validate(
        {
            "caveats": caveats or [],
            "confidence": 0.97,
            "category": "sports",
            "kalshi": {"market_id": mid, "event": "Team A vs Team B", "outcome": "Team A"},
            "polymarket_us": {"market_id": "aec-test-a", "outcome": "Team A"},
        }
    )


def leg(venue: str, side: str, price: float) -> QuoteLeg:
    return QuoteLeg(venue, "m", side, price, price, price, 50, price * 10, 0.05, NOW)  # type: ignore[arg-type]


def quote(gross: float | None, edge: float | None, contracts: int = 10, rpd: float | None = 0.5) -> Quote:
    a, b = (leg("kalshi", "yes", 0.4), leg("polymarket_us", "no", 0.5)) if gross is not None else (None, None)
    return Quote(
        a=a,
        b=b,
        contracts=contracts,
        min_edge=0.0,
        edge_at_best=edge,
        net_profit=(edge or 0) * contracts,
        net_profit_per_contract=edge or 0,
        fees=0.1,
        cost=9.0,
        return_pct=1.0,
        limited_by="size",
        as_of=NOW,
        gross_at_best=gross,
        gross_spread=(gross or 0) * contracts,
        gross_spread_per_contract=gross or 0,
        settles_at=NOW if rpd is not None else None,
        days_held=2.0 if rpd is not None else None,
        return_per_day_pct=rpd,
    )


class Fake:
    def __init__(self, q: Quote | Exception) -> None:
        self.q = q
        self.calls = 0

    def quote(self, pair, *, size=None, min_edge=0.0):  # noqa: ANN001
        self.calls += 1
        if isinstance(self.q, Exception):
            raise self.q
        return self.q


def verdict(q: Quote | Exception, s: ScanSettings = ScanSettings(), m: Match | None = None) -> dict:
    return judge(m or match(), Fake(q), s)


def test_rule_difference_goes_through_every_check_with_a_warning() -> None:
    fake = Fake(quote(0.05, 0.03))
    r = judge(match(caveats=["timing_differs"]), fake, ScanSettings())
    assert fake.calls == 1  # the books are read like any other match's
    assert r["verdict"] == "survivor" and r["quote"] is not None
    assert r["match"]["rule_warning"] == (
        "Worded differently: different deadline, measurement time or timezone. The two could settle differently."
    )


def test_rule_difference_is_dropped_only_by_the_same_checks() -> None:
    r = verdict(quote(0.01, -0.005), m=match(caveats=["source_differs"]))
    assert r["verdict"] == "fees"
    assert r["match"]["rule_warning"].startswith("Worded differently: different data source.")


def test_no_warning_when_worded_the_same_and_every_caveat_named() -> None:
    assert verdict(quote(0.05, 0.03))["match"]["rule_warning"] is None
    w = verdict(quote(0.05, 0.03), m=match(caveats=["source_differs", "rounding_differs", "new_code"]))["match"]["rule_warning"]
    assert w == (
        "Worded differently: different data source, different rounding or threshold and new code. "
        "The two could settle differently."
    )


def test_unpriced_is_a_plain_sentence_not_the_sdk_text() -> None:
    r = verdict(VenueError("stale_quote", "The polymarket_us book for x is older than max_quote_age_s.", venue="polymarket_us"))
    assert (r["verdict"], r["reason"]) == ("unpriced", "Polymarket US's prices were too old to use.")
    r = verdict(VenueError("rate_limited", "429", venue="polymarket_us"))
    assert r["reason"] == "Polymarket US asked for fewer requests; scan again in a minute."
    assert verdict(VenueError("weird_new_code", "x"))["reason"] == "A venue's prices couldn't be read right now."


def test_no_offers() -> None:
    assert verdict(quote(None, None))["verdict"] == "no_offers"


def test_no_gap() -> None:
    r = verdict(quote(-0.02, -0.04))
    assert r["verdict"] == "no_gap"
    assert r["reason"] == "Both sides together cost 102¢, before fees."  # the group says "No gap"; this doesn't


def test_fees_ate_it() -> None:
    r = verdict(quote(0.01, -0.005))
    assert r["verdict"] == "fees"
    assert r["reason"] == "A 1¢ gap before fees, −0.5¢ after."


def test_below_min_edge() -> None:
    assert verdict(quote(0.03, 0.005), ScanSettings(min_edge=0.01))["verdict"] == "below_min_edge"


def test_too_thin() -> None:
    assert verdict(quote(0.03, 0.02, contracts=0))["verdict"] == "too_thin"


def test_per_day() -> None:
    s = ScanSettings(min_return_per_day_pct=1.0)
    assert verdict(quote(0.03, 0.02, rpd=0.2), s)["verdict"] == "per_day_low"
    assert verdict(quote(0.03, 0.02, rpd=None), s)["verdict"] == "no_payout_date"
    assert verdict(quote(0.03, 0.02, rpd=1.5), s)["verdict"] == "survivor"


def test_partial_fill_survives_with_a_note() -> None:
    r = verdict(quote(0.03, 0.02, contracts=40), ScanSettings(size=100))
    assert r["verdict"] == "survivor" and "40 of 100" in r["reason"]


def test_scan_counts_every_match_once() -> None:
    events = list(scan([match("A"), match("B", ["timing_differs"])], Fake(quote(0.01, -0.01)), ScanSettings()))
    assert events[0] == {"type": "start", "total": 2, "settings": ScanSettings().__dict__}
    done = events[-1]
    assert done["counts"]["fees"] == 2 and "rules_differ" not in done["counts"]
    assert sum(done["counts"].values()) == 2
    assert [e["match"]["rule_warning"] is not None for e in events[1:-1]] == [False, True]


def test_scan_prices_several_at_once_and_keeps_the_order() -> None:
    import threading
    import time

    seen: set[int] = set()

    class Slow:
        def quote(self, pair, *, size=None, min_edge=0.0):  # noqa: ANN001, ANN202
            seen.add(threading.get_ident())
            time.sleep(0.05)
            return quote(-0.02, -0.04) if pair.kalshi.market_id.endswith("0") else quote(0.05, 0.03)

    ms = [match(f"KXTEST-{i}") for i in range(8)]
    out = list(scan(ms, Slow(), ScanSettings(), readers=4))
    rows = [e for e in out if e["type"] == "row"]
    assert [r["match"]["id"] for r in rows] == [f"KXTEST-{i}" for i in range(8)]
    assert len(seen) > 1 and out[-1]["counts"]["no_gap"] == 1 and out[-1]["counts"]["survivor"] == 7
