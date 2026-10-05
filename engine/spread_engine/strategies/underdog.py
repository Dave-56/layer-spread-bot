"""Example strategy, not advice: buy the underdog if YES is under 30¢."""

from __future__ import annotations

from uselayer import Client, Match

from . import Signal, cheapest_yes, priced

NAME = "Example: underdog under 30¢"
DESCRIPTION = "Buys 100 YES on the first upcoming outcome whose YES costs under 30¢ on either venue, never paying more than 30¢."
EXAMPLE = True
ORDER = 30
MAX = 0.30


def decide(matches: list[Match], client: Client) -> Signal | None:
    for m, p in priced(matches, client):
        yes = cheapest_yes(p)
        if yes < MAX:
            return Signal(m, "yes", 100, max_price=MAX, why=f"{m.kalshi.outcome or m.kalshi.market_id} is an underdog: YES costs {yes * 100:.0f}¢, under 30¢.")
    return None
