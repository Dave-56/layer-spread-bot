"""YOUR STRATEGY HERE.

This bot doesn't decide what to trade. Your strategy does. It looks at the markets (and anything else
you feed it) and says "buy N contracts of YES (or NO) on this outcome". The bot then does Job 1:
it compares that exact order on every venue that lists the same bet and sends it where it's cheaper
for that size, after fees.

Replace ``decide`` with your own logic. The example below is a placeholder, not advice: it picks
the first match that hasn't started, whose rules don't differ and where both venues have YES on
offer, and asks for 100 YES contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from uselayer import Client, Match, VenueError


@dataclass(frozen=True)
class Signal:
    match: Match
    side: str  # "yes" or "no": the outcome both venues' markets name
    size: int  # contracts
    max_price: float | None = None  # never pay more than this a contract (None: the SDK's price collar)
    why: str = ""


def decide(matches: list[Match], client: Client | None = None) -> Signal | None:
    """Return the trade you want, or None for no trade.

    ``client`` is the SDK client (your keys, read-only use here): ``client.prices(match)`` reads
    both venues' best bid and ask, ``client.book(...)`` a full order book.
    """
    looked = 0
    for m in matches:
        if m.caveats or not _upcoming(m):
            continue
        if client is not None:
            if looked == 10:  # each look reads two books; stop after ten
                break
            looked += 1
            try:
                p = client.prices(m)
            except VenueError:
                continue
            if p.a.yes_ask is None or p.b.yes_ask is None:
                continue
        return Signal(match=m, side="yes", size=100, why="Example stub: the first upcoming match with YES on offer on both venues, 100 YES.")
    return None


def _upcoming(m: Match) -> bool:
    when = m.kalshi.event_time or m.polymarket_us.event_time
    if not when:
        return True
    try:
        return datetime.fromisoformat(when.replace("Z", "+00:00")) > datetime.now(UTC)
    except ValueError:
        return True
