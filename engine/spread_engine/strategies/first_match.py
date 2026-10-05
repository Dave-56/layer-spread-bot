"""Example strategy, not advice: the first upcoming match, 100 YES."""

from __future__ import annotations

from uselayer import Client, Match

from . import Signal, priced

NAME = "Example: first upcoming match, 100 YES"
DESCRIPTION = "Takes the first upcoming match whose rules don't differ and where both venues sell YES, and buys 100 YES."
EXAMPLE = True
ORDER = 10


def decide(matches: list[Match], client: Client) -> Signal | None:
    for m, _ in priced(matches, client):
        return Signal(m, "yes", 100, why=f"It's the first upcoming match with YES on offer on both venues ({m.kalshi.outcome or m.kalshi.market_id}).")
    return None
