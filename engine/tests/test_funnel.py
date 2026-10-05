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


def test_rules_differ_drops_before_reading_books() -> None:
    fake = Fake(quote(0.05, 0.03))
    r = judge(match(caveats=["timing_differs"]), fake, ScanSettings())
    assert r["verdict"] == "rules_differ"
    assert "deadline" in r["reason"]
    assert fake.calls == 0 and r["quote"] is None


def test_rules_differ_can_be_kept() -> None:
    r = verdict(quote(0.05, 0.03), ScanSettings(skip_rule_differences=False), match(caveats=["source_differs"]))
    assert r["verdict"] == "survivor"


def test_unpriced() -> None:
    r = verdict(VenueError("stale_book", "The Kalshi book is stale."))
    assert r["verdict"] == "unpriced" and "stale" in r["reason"]


def test_no_offers() -> None:
    assert verdict(quote(None, None))["verdict"] == "no_offers"


def test_no_gap() -> None:
    r = verdict(quote(-0.02, -0.04))
    assert r["verdict"] == "no_gap"
    assert "102.0¢" in r["reason"]


def test_fees_ate_it() -> None:
    r = verdict(quote(0.01, -0.005))
    assert r["verdict"] == "fees"
    assert "1.0¢" in r["reason"] and "-0.5¢" in r["reason"]


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
    assert done["counts"]["fees"] == 1 and done["counts"]["rules_differ"] == 1
    assert sum(done["counts"].values()) == 2
