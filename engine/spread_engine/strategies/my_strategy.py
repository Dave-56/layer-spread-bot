"""YOUR STRATEGY. Copy this file (e.g. to strategies/momentum.py), give it a NAME, write decide().

It shows up in the app's strategy picker on the Best venue tab. Edits are picked up the next time you
press "Run strategy"; a new file appears after you reload the page.
"""

from __future__ import annotations

from uselayer import Client, Match

from . import Signal, priced

NAME = "My strategy (template)"
DESCRIPTION = "Your logic goes here: engine/spread_engine/strategies/my_strategy.py. Until you write it, it makes no trade."
ORDER = 90


def decide(matches: list[Match], client: Client) -> Signal | None:
    # `matches`: markets Layer says are the same bet on Kalshi and Polymarket US (the search on screen).
    #   m.kalshi.outcome, m.kalshi.event_time, m.caveats (rule differences), m.polymarket_us.market_id ...
    # `client`: the uselayer SDK with your own keys. Read anything you need:
    #   p = client.prices(m)  → p.a.yes_ask, p.b.yes_ask, p.leg("kalshi").no_bid ...
    #   client.book(m.kalshi)  → a full order book
    # `priced(matches, client)` gives you upcoming, rule-clean matches with both venues' prices.
    #
    # Write your logic here: which market, YES or NO, how many contracts, and the most you'll pay.
    #
    # for m, p in priced(matches, client):
    #     if <your condition on m and p>:
    #         return Signal(m, "yes", 50, max_price=0.60, why="<one line on why>")
    return None  # no trade
