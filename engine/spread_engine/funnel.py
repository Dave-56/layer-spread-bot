"""Job 2, cross-venue arbitrage: scan matched markets and say what happened to every gap.

Each match goes through the same gates, in order, and stops at the first it fails:

1. rules_differ    Layer flagged a rule difference between the two markets (its caveats).
2. unpriced        A book couldn't be read (no key, stale book, the venue didn't answer).
3. no_offers       One venue has nobody selling one side.
4. no_gap          YES on one venue plus NO on the other costs $1.00 or more before fees.
5. fees            There is a gap, but both venues' fees are bigger than it.
6. below_min_edge  Something is left after fees, but less than your minimum per contract.
7. too_thin        The books can't fill even one contract that clears your minimum.
8. no_payout_date  You asked for a return per day, and neither venue gives a payout time.
9. per_day_low     The return per day is below your minimum.

What's left is a survivor: gross spread → fees → net → return per day, all from ``client.quote()``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from uselayer import Match, Quote, VenueError

from .views import VENUE_NAMES, error_view, match_view

GATES = (
    "rules_differ",
    "unpriced",
    "no_offers",
    "no_gap",
    "fees",
    "below_min_edge",
    "too_thin",
    "no_payout_date",
    "per_day_low",
)


# Layer's codes: same event and outcome normally, but the rules differ on an edge case.
CAVEATS = {
    "source_differs": "different data source",
    "timing_differs": "different deadline, measurement time or timezone",
    "rounding_differs": "different rounding or threshold",
    "carveout_differs": "different special exceptions (e.g. ambiguity rules)",
    "definition_differs": "a term is defined differently",
}


class Quoter(Protocol):
    def quote(self, pair: Any, *, size: int | None = None, min_edge: float = 0.0) -> Quote: ...


@dataclass(frozen=True)
class ScanSettings:
    size: int = 100
    min_edge: float = 0.0  # $ per contract after fees
    min_return_per_day_pct: float = 0.0
    skip_rule_differences: bool = True


def cents(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}¢"


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

    # Checked before any book is read: most of a scan's time is reading books.
    if s.skip_rule_differences and m.caveats:
        return drop("rules_differ", "Rules differ: " + ", ".join(CAVEATS.get(c, c) for c in m.caveats) + ".")

    try:
        q = client.quote(m, size=s.size, min_edge=s.min_edge)
    except VenueError as e:
        return drop("unpriced", "Couldn't price it: " + error_view(e)["message"])
    row["quote"] = quote_view(q)

    if q.a is None or q.b is None or q.gross_at_best is None or q.edge_at_best is None:
        return drop("no_offers", "No offers on one venue, so there's nothing to buy on one side.")
    gross, edge = q.gross_at_best, q.edge_at_best
    if gross <= 0:
        return drop(
            "no_gap",
            f"No gap: YES on one venue and NO on the other cost {cents(1 - gross)} together, before fees.",
        )
    if edge <= 0:
        return drop(
            "fees",
            f"Fees are bigger than the gap: {cents(gross)} a contract before fees, {cents(edge)} after.",
        )
    if edge <= s.min_edge:
        return drop(
            "below_min_edge",
            f"{cents(edge)} a contract after fees is below your minimum of {cents(s.min_edge)}.",
        )
    if q.contracts < 1:
        return drop("too_thin", "Too thin: the books can't fill one contract that clears your minimum.")
    if s.min_return_per_day_pct > 0:
        if q.return_per_day_pct is None:
            return drop("no_payout_date", "Neither venue gives a payout date, so there's no return per day.")
        if q.return_per_day_pct < s.min_return_per_day_pct:
            return drop(
                "per_day_low",
                f"Return per day {q.return_per_day_pct:.3f}% is below your minimum of "
                f"{s.min_return_per_day_pct:g}% ({q.return_pct:.2f}% over {q.days_held:g} days).",
            )
    row["verdict"] = "survivor"
    if q.contracts < s.size:
        row["reason"] = f"Only {q.contracts} of {s.size} contracts clear: {q.limited_by}."
    return row


def scan(matches: list[Match], client: Quoter, s: ScanSettings) -> Iterator[dict[str, Any]]:
    """Stream the funnel: a ``start`` event, one ``row`` per match, then ``done`` with the counts."""
    counts = {g: 0 for g in GATES} | {"survivor": 0}
    yield {"type": "start", "total": len(matches), "settings": s.__dict__}
    for m in matches:
        row = judge(m, client, s)
        counts[row["verdict"]] += 1
        yield {"type": "row", **row}
    yield {"type": "done", "total": len(matches), "counts": counts}
