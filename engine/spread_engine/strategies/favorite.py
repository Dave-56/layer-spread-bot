"""Example strategy, not advice: buy the favorite."""

from __future__ import annotations

from uselayer import Client, Match

from . import Signal, cheapest_yes, priced

NAME = "Example: buy the favorite"
DESCRIPTION = "Of the first ten upcoming matches, buys 100 YES on the outcome the market prices highest (the favorite)."
EXAMPLE = True
ORDER = 20


def decide(matches: list[Match], client: Client) -> Signal | None:
    best = None
    for m, p in priced(matches, client):
        yes = cheapest_yes(p)
        if best is None or yes > best[1]:
            best = (m, yes)
    if best is None or best[1] < 0.5:
        return None
    m, yes = best
    return Signal(m, "yes", 100, why=f"{m.kalshi.outcome or m.kalshi.market_id} is the favorite: YES costs {yes * 100:.0f}¢, the highest of the matches it looked at.")
