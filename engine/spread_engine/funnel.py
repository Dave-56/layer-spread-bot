"""Job 2, cross-venue arbitrage: scan matched markets and say what happened to every gap.

Each match goes through the same gates, in order, and stops at the first it fails:

1. unpriced        A book couldn't be read (no key, stale book, the venue didn't answer).
2. no_offers       One venue has nobody selling one side.
3. no_gap          YES on one venue plus NO on the other costs $1.00 or more before fees.
4. fees            There is a gap, but both venues' fees are bigger than it.
5. below_min_edge  Something is left after fees, but less than your minimum per contract.
6. too_thin        The books can't fill even one contract that clears your minimum.
7. no_payout_date  You asked for a return per day, and neither venue gives a payout time.
8. per_day_low     The return per day is below your minimum.

What's left is a survivor: gross spread → fees → net → return per day, all from ``client.quote()``.

A match where Layer flagged a rule difference (a different data source, deadline, rounding, exception
or definition) goes through the same gates as any other. It is never dropped for it: its
``match.rule_warning`` says how the two are worded differently, and it travels with the match.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from uselayer import Match, Quote, VenueError

from .views import VENUE_NAMES, match_view, price_error

GATES = (
    "unpriced",
    "no_offers",
    "no_gap",
    "fees",
    "below_min_edge",
    "too_thin",
    "no_payout_date",
    "per_day_low",
)


class Quoter(Protocol):
    def quote(self, pair: Any, *, size: int | None = None, min_edge: float = 0.0) -> Quote: ...


@dataclass(frozen=True)
class ScanSettings:
    size: int = 100
    min_edge: float = 0.0  # $ per contract after fees
    min_return_per_day_pct: float = 0.0


def cents(x: float | None) -> str:
    """``1¢``, ``0.6¢``, ``−0.6¢``: at most one decimal, none when it's whole."""
    if x is None:
        return "—"
    c = round(x * 100, 1)
    return f"{'−' if c < 0 else ''}{abs(c):g}¢"


def quote_view(q: Quote) -> dict[str, Any]:
    def leg(lg: Any) -> dict[str, Any] | None:
        if lg is None:
            return None
        return {
            "venue": lg.venue,
            "venue_name": VENUE_NAMES.get(lg.venue, lg.venue),
            "market": lg.market,
            "side": lg.side,
            "best_price": lg.best_price,
            "limit_price": lg.limit_price,
            "average_price": lg.average_price,
            "contracts_at_best": lg.contracts_at_best,
            "cost": lg.cost,
            "fee": lg.fee,
            "book_as_of": lg.book_as_of.isoformat(),
        }

    return {
        "a": leg(q.a),
        "b": leg(q.b),
        "contracts": q.contracts,
        "gross_at_best": q.gross_at_best,
        "edge_at_best": q.edge_at_best,
        "gross_spread": q.gross_spread,
        "fees": q.fees,
        "net_profit": q.net_profit,
        "net_profit_per_contract": q.net_profit_per_contract,
        "cost": q.cost,
        "return_pct": q.return_pct,
        "days_held": q.days_held,
        "return_per_day_pct": q.return_per_day_pct,
        "settles_at": q.settles_at.isoformat() if q.settles_at else None,
        "limited_by": q.limited_by,
        "as_of": q.as_of.isoformat(),
    }


def judge(m: Match, client: Quoter, s: ScanSettings) -> dict[str, Any]:
    """One match through the gates: ``{"match", "verdict", "reason", "quote"}``."""
    row: dict[str, Any] = {"match": match_view(m), "verdict": None, "reason": None, "quote": None}

    def drop(gate: str, reason: str) -> dict[str, Any]:
        row["verdict"] = gate
        row["reason"] = reason
        return row

    try:
        q = client.quote(m, size=s.size, min_edge=s.min_edge)
    except VenueError as e:
        return drop("unpriced", price_error(e))
    row["quote"] = quote_view(q)

    # Each reason is one plain sentence that adds to its group's name ("No gap"), never repeats it.
    if q.a is None or q.b is None or q.gross_at_best is None or q.edge_at_best is None:
        return drop("no_offers", "Nobody is selling on one of the two venues.")
    gross, edge = q.gross_at_best, q.edge_at_best
    if gross <= 0:
        return drop("no_gap", f"Both sides together cost {cents(1 - gross)}, before fees.")
    if edge <= 0:
        return drop("fees", f"A {cents(gross)} gap before fees, {cents(edge)} after.")
    if edge <= s.min_edge:
        return drop("below_min_edge", f"{cents(edge)} a contract after fees; your minimum is {cents(s.min_edge)}.")
    if q.contracts < 1:
        return drop("too_thin", "Not enough for sale to buy even one contract at a profit.")
    if s.min_return_per_day_pct > 0:
        if q.return_per_day_pct is None:
            return drop("no_payout_date", "Neither venue says when it pays out.")
        if q.return_per_day_pct < s.min_return_per_day_pct:
            return drop(
                "per_day_low",
                f"{q.return_per_day_pct:.3f}% a day ({q.return_pct:.2f}% over {q.days_held:g} days); "
                f"your minimum is {s.min_return_per_day_pct:g}%.",
            )
    row["verdict"] = "survivor"
    if q.contracts < s.size:
        row["reason"] = f"Only {q.contracts} of {s.size} contracts are still a profit."
    return row


def scan(matches: list[Match], client: Quoter, s: ScanSettings, *, readers: int = 1) -> Iterator[dict[str, Any]]:
    """Stream the funnel: a ``start`` event, one ``row`` per match, then ``done`` with the counts.

    ``readers`` matches are priced at once (each is both venues' books), and rows come in match order.
    """
    counts = {g: 0 for g in GATES} | {"survivor": 0}
    yield {"type": "start", "total": len(matches), "settings": s.__dict__}
    pool = ThreadPoolExecutor(max_workers=max(1, readers))
    try:
        for row in pool.map(lambda m: judge(m, client, s), matches):
            counts[row["verdict"]] += 1
            yield {"type": "row", **row}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # the app stopped reading: stop pricing
    yield {"type": "done", "total": len(matches), "counts": counts}
