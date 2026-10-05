"""Example strategy, not advice: buy YES where the two venues disagree most."""

from __future__ import annotations

from uselayer import Client, Match

from . import Signal, priced

NAME = "Example: venues disagree"
DESCRIPTION = "Of the first ten upcoming matches, buys 100 YES on the one whose YES price differs most between Kalshi and Polymarket US."
EXAMPLE = True
ORDER = 40


def decide(matches: list[Match], client: Client) -> Signal | None:
    best = None
    for m, p in priced(matches, client):
        gap = abs((p.a.yes_ask or 0) - (p.b.yes_ask or 0))
        if best is None or gap > best[1]:
            best = (m, gap, p)
    if best is None:
        return None
    m, gap, p = best
    return Signal(
        m,
        "yes",
        100,
        why=f"Kalshi asks {p.leg('kalshi').yes_ask * 100:.0f}¢ and Polymarket US {p.leg('polymarket_us').yes_ask * 100:.0f}¢ for YES on {m.kalshi.outcome or m.kalshi.market_id}: a {gap * 100:.0f}¢ difference, the widest it saw.",
    )
