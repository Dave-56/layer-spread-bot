"""Example strategy, not advice: the first upcoming match, 100 YES."""

from __future__ import annotations

from uselayer import Client, Match

from . import Signal, priced

NAME = "Example: first upcoming match, 100 YES"
DESCRIPTION = "Takes the first upcoming match that's open on both venues, worded the same on both, with a real YES price on each, and buys 100 YES."
EXAMPLE = True
ORDER = 10


def decide(matches: list[Match], client: Client) -> Signal | None:
    for m, _ in priced(matches, client):
        return Signal(m, "yes", 100, why=f"It's the first upcoming match that's open on both venues with a real YES price on each ({m.kalshi.outcome or m.kalshi.market_id}).")
    return None
